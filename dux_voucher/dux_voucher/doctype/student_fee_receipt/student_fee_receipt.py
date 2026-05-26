"""Student Fee Receipt — admission-fee collection from incoming students.

Single submittable doctype. On submit it posts one Journal Entry
crediting the company's 'Admission/Registration Fee (Provisional)'
liability (under the Admission Fee (Provisional) group, under Current
Liabilities) and debiting the bank/cash account on the receipt; on
cancel it cancels that JE. The JE is the only side-effect; the heads
child table is purely a presentation device for the printed receipt.

Cancel-cascade in both directions piggy-backs on the existing
``utils.on_journal_entry_cancel`` hook — no new wiring needed because
the hook reads ``custom_source_voucher_doctype`` / ``custom_source_voucher``
generically.
"""

from datetime import date

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


# =====================================================================
# Public dotted helper — used by the JS form to seed admission_year
# without re-implementing the FY math in the browser.
# =====================================================================

@frappe.whitelist()
def current_admission_year(today=None):
    """Indian fiscal year of ``today`` (default: server today) in the
    'FY YYYY-YY' format. Apr-Mar fiscal year boundary.

    Examples:
        2026-05-01 → "FY 2026-27"
        2027-02-15 → "FY 2026-27"
        2027-04-01 → "FY 2027-28"
    """
    today = getdate(today) if today else getdate()
    start = today.year if today.month >= 4 else today.year - 1
    end_yy = (start + 1) % 100
    return f"FY {start}-{end_yy:02d}"


# =====================================================================
# Controller
# =====================================================================

class StudentFeeReceipt(Document):

    # ── Lifecycle ────────────────────────────────────────────────────

    def insert(self, *args, **kwargs):
        """Wipe inherited ``backend_je`` + reset ``is_posted`` on
        amendment *before* Frappe runs its cancelled-link validation.

        Frappe's amend flow copies the cancelled doc whole — including
        ``backend_je``, which points at the now-cancelled Journal Entry.
        ``Document.insert`` then runs ``_validate_links()`` ahead of
        ``before_insert``, so a ``before_insert`` cleanup is too late:
        it has already thrown ``Cannot link cancelled document``.

        Overriding ``insert()`` lets us scrub the field in the narrow
        window between the doc being instantiated and the lifecycle
        starting. The fresh submission will repopulate ``backend_je``
        with the new JE posted by ``on_submit``, so the inherited value
        is pure garbage. Mirrors the Payment Voucher / Receipt Voucher
        fix.
        """
        if self.amended_from:
            self.backend_je = None
            self.is_posted = 0
        return super().insert(*args, **kwargs)

    def before_insert(self):
        """Populate ``admission_year`` if the form / API caller didn't
        provide one. The field is required, but defaulting here means
        a happy-path counter operator never sees a 'fill this in'
        prompt — it's already correct."""
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
        # ``db_set`` writes through to DB without re-running validate /
        # on_update — exactly what we want for a submit-time bookkeeping
        # update on the parent. Mirrors the existing PV / RV pattern.
        self.db_set("backend_je", je_name)
        self.db_set("is_posted", 1)

    def on_cancel(self):
        """Cancel the linked JE if it's still active. ``_safe_cancel``
        is idempotent — if the JE was cancelled already (e.g. via the
        cascade hook from JE → receipt), this is a no-op."""
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
        if not self.received_in_account:
            frappe.throw(_("Received In Account is required."))
        if not self.admission_year:
            frappe.throw(_("Admission Year is required."))

    def _validate_student_consistency(self):
        """The student's company must match the receipt's company. If
        they don't, either the student was created at a different
        institution (legitimate but the receipt should be filed at
        that institution, not this one) or the company was changed
        after the student was picked. Either way, refuse rather than
        post a JE in the wrong company's books."""
        student_company = frappe.db.get_value(
            "Student", self.student, "company"
        )
        if student_company and student_company != self.company:
            frappe.throw(
                _("Student '{0}' is enrolled at {1}, not {2}. Pick a "
                  "student from the same company as the receipt, or "
                  "switch the receipt's company.")
                .format(self.student, student_company, self.company)
            )

    def _validate_heads(self):
        if not self.heads:
            frappe.throw(_("Add at least one fee head row."))

        # All rows must reference heads that belong to the student's
        # course. We do this in one round-trip: fetch the student's
        # course and the per-head course in single queries.
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
        """Recompute ``total_amount`` from the head rows on every save
        so the value is always trustworthy. Read-only on the form, so
        the user can't tamper with it directly — but a stale value
        could land via API/import, hence the recompute."""
        total = sum(flt(row.amount) for row in self.heads)
        self.total_amount = total
        if total <= 0:
            frappe.throw(_("Total Amount must be greater than zero."))

    def _validate_account(self):
        _validate_bank_cash_account(
            self.received_in_account, "Received In Account"
        )
        # Account must belong to the same company as the receipt —
        # otherwise the JE would mix companies, which ERPNext rejects
        # later but with a less-friendly error.
        acc_company = frappe.db.get_value(
            "Account", self.received_in_account, "company"
        )
        if acc_company and acc_company != self.company:
            frappe.throw(
                _("Account '{0}' belongs to {1}, not {2}.")
                .format(self.received_in_account, acc_company, self.company)
            )

    # ── JE posting ───────────────────────────────────────────────────

    def _post_journal_entry(self):
        """Build and submit the single 2-line JE for this receipt.

        Lines:
          Cr  'Admission Fee / Registration - {abbr}'   total_amount
          Dr  received_in_account                       total_amount

        ``voucher_type`` is derived from the received-in account's
        type (Bank vs Cash) so ERPNext's bank-reconciliation flows
        pick up the entry correctly.
        """
        admission_fee = get_admission_fee_account(self.company)

        account_type = frappe.db.get_value(
            "Account", self.received_in_account, "account_type"
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
            or _("Admission fee — {0} ({1})").format(
                self.student_name or self.student, self.admission_year
            )
        )
        je.custom_source_voucher_doctype = "Student Fee Receipt"
        je.custom_source_voucher = self.name

        # Cr admission fee liability — fees collected on behalf of the
        # university, owed forward.
        je.append("accounts", {
            "account":                       admission_fee,
            "credit_in_account_currency":    flt(self.total_amount),
            "debit_in_account_currency":     0,
            "user_remark":                   _("From {0}").format(
                self.student_name or self.student
            ),
        })

        # Dr cash/bank — money in.
        je.append("accounts", {
            "account":                       self.received_in_account,
            "debit_in_account_currency":     flt(self.total_amount),
            "credit_in_account_currency":    0,
        })

        _submit_doc(je)
        return je.name
