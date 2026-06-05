"""Student Fee Refund — refund admission fees to a new student.

Mirror of Student Fee Receipt with the JE legs swapped:

    Receipt   Dr Bank/Cash                      Cr Admission Fee
    Refund    Dr Admission Fee                  Cr Bank/Cash

Same liability account is touched in both directions — receipts go Cr,
refunds go Dr, balance = net fees held. There is no separate "refund
payable" account.

Why a separate doctype rather than a negative Receipt?
  * Explicit intent on the ledger and on the printed voucher.
  * Soft-warn checks (no receipts on file / refund exceeds paid) are
    meaningful only in the refund direction.
  * Print format with a different accent makes the operator's
    direction unambiguous when handing the printed voucher to the
    student.

Cancel-cascade in both directions reuses the existing
``utils.on_journal_entry_cancel`` hook — no new wiring needed, the
hook is doctype-agnostic.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, getdate

from dux_voucher.dux_voucher.api.utils import (
    _validate_bank_cash_account,
    _submit_doc,
    _safe_cancel,
)
from dux_voucher.dux_voucher.api.student_fee import (
    get_admission_fee_account,
)
from dux_voucher.dux_voucher.doctype.student_fee_receipt.student_fee_receipt import (
    current_admission_year,
)


class StudentFeeRefund(Document):

    # ── Lifecycle ────────────────────────────────────────────────────

    def insert(self, *args, **kwargs):
        """Wipe ``backend_je`` + reset ``is_posted`` on amendment
        *before* Frappe runs its cancelled-link validation.

        Same pattern as Student Fee Receipt / Ex Student Refund /
        Payment Voucher / Receipt Voucher — see those modules for the
        full rationale.
        """
        if self.amended_from:
            self.backend_je = None
            self.is_posted = 0
        return super().insert(*args, **kwargs)

    def before_insert(self):
        """Default admission_year to the current Indian FY if blank.
        Mirrors the Receipt's defaulter so a counter operator never
        sees an empty required field."""
        if not self.admission_year:
            self.admission_year = current_admission_year(self.posting_date)

    def validate(self):
        self._validate_basic()
        self._validate_student_consistency()
        self._validate_heads()
        self._compute_total()
        self._validate_account()

    def on_submit(self):
        """Post a single 2-line JE and stamp ``backend_je`` + ``is_posted``."""
        je_name = self._post_journal_entry()
        self.db_set("backend_je", je_name)
        self.db_set("is_posted", 1)

    def on_cancel(self):
        """Cancel the linked JE if it's still active. ``_safe_cancel``
        is idempotent — if the JE was cancelled already (e.g. via the
        cascade hook from JE → refund), this is a no-op."""
        if self.backend_je:
            _safe_cancel("Journal Entry", self.backend_je)
        self.db_set("is_posted", 0)

    # ── Validations ──────────────────────────────────────────────────

    def _validate_basic(self):
        if not self.company:
            frappe.throw(_("Company is required."))
        if not self.posting_date:
            frappe.throw(_("Posting Date is required."))
        if not self.student:
            frappe.throw(_("Student is required."))
        if not self.paid_from_account:
            frappe.throw(_("Paid From Account is required."))
        if not self.admission_year:
            frappe.throw(_("Admission Year is required."))

    def _validate_student_consistency(self):
        """The student's company must match the refund's company."""
        student_company = frappe.db.get_value(
            "Student", self.student, "company"
        )
        if student_company and student_company != self.company:
            frappe.throw(
                _("Student '{0}' is enrolled at {1}, not {2}. Pick a "
                  "student from the same company as the refund, or "
                  "switch the refund's company.")
                .format(self.student, student_company, self.company)
            )

    def _validate_heads(self):
        if not self.heads:
            frappe.throw(_("Add at least one fee head row."))

        student_course = frappe.db.get_value(
            "Student", self.student, "course"
        )
        if not student_course:
            frappe.throw(
                _("Student '{0}' has no course on the master record.")
                .format(self.student)
            )

        for row in self.heads:
            if not row.head:
                frappe.throw(
                    _("Row {0}: Fee Head is required.").format(row.idx)
                )
            head_course = frappe.db.get_value(
                "Course Fee Head", row.head, "course"
            )
            if head_course != student_course:
                head_label = (frappe.db.get_value(
                    "Course Fee Head", row.head, "head_name"
                ) or row.head)
                frappe.throw(
                    _("Row {0}: Fee head '{1}' is for course '{2}', "
                      "not the student's course '{3}'.")
                    .format(row.idx, head_label, head_course,
                             student_course)
                )
            if flt(row.amount) <= 0:
                frappe.throw(
                    _("Row {0}: Amount must be greater than zero.")
                    .format(row.idx)
                )

    def _compute_total(self):
        """Recompute ``total_amount`` from the head rows on every save."""
        total = sum(flt(row.amount) for row in self.heads)
        self.total_amount = total
        if total <= 0:
            frappe.throw(_("Total Refund must be greater than zero."))

    def _validate_account(self):
        _validate_bank_cash_account(
            self.paid_from_account, "Paid From Account"
        )
        acc_company = frappe.db.get_value(
            "Account", self.paid_from_account, "company"
        )
        if acc_company and acc_company != self.company:
            frappe.throw(
                _("Account '{0}' belongs to {1}, not {2}.")
                .format(self.paid_from_account, acc_company, self.company)
            )

    # ── JE posting ───────────────────────────────────────────────────

    def _post_journal_entry(self):
        """Build and submit the single 2-line JE for this refund.

        Lines (mirror of Receipt's JE, legs swapped):
          Dr  'Admission/Registration Fee (Provisional) - {abbr}'  total
          Cr  paid_from_account                                    total

        ``voucher_type`` derives from the paid-from account's type
        (Bank vs Cash) so ERPNext's bank-reconciliation flows pick up
        the entry correctly.
        """
        admission_fee = get_admission_fee_account(self.company)

        account_type = frappe.db.get_value(
            "Account", self.paid_from_account, "account_type"
        )
        voucher_type = "Cash Entry" if account_type == "Cash" else "Bank Entry"

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = voucher_type
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or ""
        je.cheque_date = self.reference_date or None
        je.user_remark = (
            self.remarks
            or _("Admission fee refund — {0} ({1})").format(
                self.student_name or self.student, self.admission_year
            )
        )
        je.custom_source_voucher_doctype = "Student Fee Refund"
        je.custom_source_voucher = self.name

        # Dr the admission fee liability — reversing what the original
        # receipt(s) credited. Drives the liability back toward zero.
        je.append("accounts", {
            "account":                       admission_fee,
            "debit_in_account_currency":     flt(self.total_amount),
            "credit_in_account_currency":    0,
            "user_remark":                   _("To {0}").format(
                self.student_name or self.student
            ),
        })

        # Cr bank/cash — money out.
        je.append("accounts", {
            "account":                       self.paid_from_account,
            "debit_in_account_currency":     0,
            "credit_in_account_currency":    flt(self.total_amount),
        })

        _submit_doc(je)
        return je.name
