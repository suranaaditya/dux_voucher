"""Ex Student Refund — pay a credit balance back to an ex-student.

Mirror of Ex Student Receipt: same form, same backend-JE pattern, same
cancel cascade, but the JE legs are reversed (Dr Receivable, Cr Bank /
Cash) and the ledger entry is on the *debit* side.

Why a separate doctype rather than allowing negative Receipts: an
explicit Refund makes the intent unambiguous on the ledger, on the
Outstanding report, and on the printed voucher. It also keeps the
overpayment-warning UX on Receipts clean — Receipts always increase
the credit, Refunds always reduce it.

Both directions of the cancel cascade are reused as-is:
* Refund cancelled in the UI    -> backend JE cancelled via _safe_cancel
* Backend JE cancelled directly -> ``utils.on_journal_entry_cancel``
  hook reads ``custom_source_voucher_doctype`` / ``custom_source_voucher``
  and cancels the Refund. The hook is doctype-agnostic, so adding
  Refund to the universe requires no hook change.
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dux_voucher.dux_voucher.api.utils import (
    _get_ex_student_accounts,
    _get_account_currency,
    _validate_bank_cash_account,
    _submit_doc,
    _safe_cancel,
)


class ExStudentRefund(Document):

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def insert(self, *args, **kwargs):
        """Wipe ``backend_je`` + reset ``is_posted`` on amendment *before*
        Frappe's ``_validate_links`` runs and refuses the inherited
        cancelled-JE link.

        Same pattern as Student Fee Receipt / Payment Voucher /
        Receipt Voucher — see those modules for the full rationale.
        """
        if self.amended_from:
            self.backend_je = None
            self.is_posted = 0
        return super().insert(*args, **kwargs)

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------
    def validate(self):
        if not self.company:
            frappe.throw(_('Company is required'))
        if not self.posting_date:
            frappe.throw(_('Posting Date is required'))
        if not self.ex_student:
            frappe.throw(_('Ex Student is required'))
        if flt(self.amount) <= 0:
            frappe.throw(_('Refund Amount must be greater than zero'))
        if not self.mode_of_payment:
            frappe.throw(_('Payment Method is required'))
        if not self.paid_from_account:
            frappe.throw(_('Paid From Account is required'))

        # Student must belong to the same company
        student_company = frappe.db.get_value(
            'Ex Student', self.ex_student, 'company'
        )
        if student_company != self.company:
            frappe.throw(_(
                'Ex Student {0} belongs to company {1}, not {2}'
            ).format(self.ex_student, student_company, self.company))

        # Paid From Account must be Bank or Cash and match the company
        acc_company = frappe.db.get_value(
            'Account', self.paid_from_account, 'company'
        )
        if acc_company != self.company:
            frappe.throw(_(
                'Paid From Account {0} belongs to company {1}, not {2}'
            ).format(self.paid_from_account, acc_company, self.company))
        _validate_bank_cash_account(
            self.paid_from_account, _('Paid From Account')
        )

        # Ensure the Ex-Students Receivable control account exists.
        # (Temporary Opening isn't used by refunds but the resolver
        # checks both for consistency with Receipt / Writeoff.)
        _get_ex_student_accounts(self.company)

    # ------------------------------------------------------------------
    # On Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        from dux_voucher.dux_voucher.api.ex_student_api import (
            _current_outstanding,
        )

        outstanding_before = _current_outstanding(self.ex_student)
        # A refund DEBITS the ex-student's running balance (moves Cr
        # back toward zero, or pushes Dr higher if there was no credit
        # to begin with — the soft warn in the JS already flagged that
        # to the operator).
        outstanding_after = outstanding_before + flt(self.amount)

        je_name = self._create_refund_journal_entry()
        self._insert_ledger_entry(je_name)

        self.db_set('backend_je', je_name, update_modified=False)
        self.db_set('is_posted', 1, update_modified=False)
        self.db_set('outstanding_before', outstanding_before,
                    update_modified=False)
        self.db_set('outstanding_after', outstanding_after,
                    update_modified=False)

        student = frappe.get_doc('Ex Student', self.ex_student)
        student.recompute_opening_balance()

    def _create_refund_journal_entry(self):
        """Post a single 2-line JE — mirror of Receipt's JE with the
        legs swapped:

            Dr   Ex-Students Receivable - {abbr}    amount
                Cr   self.paid_from_account         amount
        """
        receivable_account, _opening = _get_ex_student_accounts(self.company)
        currency = _get_account_currency(self.paid_from_account, self.company)

        je = frappe.new_doc('Journal Entry')
        # Voucher type derives from the paid-from account so ERPNext's
        # bank-reconciliation tooling picks the entry up correctly.
        acc_type = (
            frappe.db.get_value('Account', self.paid_from_account,
                                'account_type')
            or 'Bank'
        )
        je.voucher_type = 'Cash Entry' if acc_type == 'Cash' else 'Bank Entry'
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or self.name
        je.cheque_date = self.reference_date or self.posting_date
        je.user_remark = self.remarks or _(
            'Ex-student refund to {0}'
        ).format(self.student_name or self.ex_student)
        je.custom_source_voucher_doctype = 'Ex Student Refund'
        je.custom_source_voucher = self.name

        # Debit: Ex-Students Receivable — reduces the credit balance
        # (or increases Dr if the student had none).
        je.append('accounts', {
            'account': receivable_account,
            'account_currency': currency,
            'debit_in_account_currency': flt(self.amount),
            'credit_in_account_currency': 0,
        })
        # Credit: Paid From Account (Bank/Cash) — money out.
        je.append('accounts', {
            'account': self.paid_from_account,
            'account_currency': currency,
            'debit_in_account_currency': 0,
            'credit_in_account_currency': flt(self.amount),
        })

        _submit_doc(je)
        return je.name

    def _insert_ledger_entry(self, je_name):
        """One row in the denormalised Ex Student Ledger Entry register.

        ``debit = amount`` — mirror of Receipt's ``credit = amount``.
        ``Ex Student.recompute_opening_balance()`` reads
        ``SUM(debit) - SUM(credit)`` so the new row naturally moves a
        Cr balance toward zero (or pushes Dr higher).
        """
        ledger = frappe.new_doc('Ex Student Ledger Entry')
        ledger.ex_student = self.ex_student
        ledger.company = self.company
        ledger.posting_date = self.posting_date
        ledger.debit = flt(self.amount)
        ledger.credit = 0
        ledger.voucher_type = 'Ex Student Refund'
        ledger.voucher_no = self.name
        ledger.remarks = self.remarks or _(
            'Refund ({0})'
        ).format(self.mode_of_payment)
        ledger.is_cancelled = 0
        ledger.insert(ignore_permissions=True)

    # ------------------------------------------------------------------
    # On Cancel
    # ------------------------------------------------------------------
    def on_cancel(self):
        if self.backend_je:
            _safe_cancel('Journal Entry', self.backend_je)

        frappe.db.sql(
            '''
            UPDATE `tabEx Student Ledger Entry`
            SET is_cancelled = 1
            WHERE voucher_type = 'Ex Student Refund'
              AND voucher_no = %s
            ''',
            (self.name,),
        )

        self.db_set('is_posted', 0, update_modified=False)

        if self.ex_student and frappe.db.exists('Ex Student', self.ex_student):
            student = frappe.get_doc('Ex Student', self.ex_student)
            student.recompute_opening_balance()
