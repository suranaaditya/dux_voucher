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


class ExStudentReceipt(Document):

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
            frappe.throw(_('Amount must be greater than zero'))
        if not self.mode_of_payment:
            frappe.throw(_('Payment Method is required'))
        if not self.received_in_account:
            frappe.throw(_('Received In Account is required'))

        # Student must belong to the same company
        student_company = frappe.db.get_value('Ex Student', self.ex_student, 'company')
        if student_company != self.company:
            frappe.throw(_(
                'Ex Student {0} belongs to company {1}, not {2}'
            ).format(self.ex_student, student_company, self.company))

        # Received In Account must be Bank or Cash and match the company
        acc_company = frappe.db.get_value('Account', self.received_in_account, 'company')
        if acc_company != self.company:
            frappe.throw(_(
                'Received In Account {0} belongs to company {1}, not {2}'
            ).format(self.received_in_account, acc_company, self.company))
        _validate_bank_cash_account(self.received_in_account, _('Received In Account'))

        # Ensure the Ex-Students Receivable + Temporary Opening accounts exist
        # (Temporary Opening isn't used by receipts but we check here for consistency)
        _get_ex_student_accounts(self.company)

    # ------------------------------------------------------------------
    # On Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        from dux_voucher.dux_voucher.api.ex_student_api import _current_outstanding

        outstanding_before = _current_outstanding(self.ex_student)
        outstanding_after = outstanding_before - flt(self.amount)

        je_name = self._create_receipt_journal_entry()
        self._insert_ledger_entry(je_name)

        self.db_set('backend_je', je_name, update_modified=False)
        self.db_set('is_posted', 1, update_modified=False)
        self.db_set('outstanding_before', outstanding_before, update_modified=False)
        self.db_set('outstanding_after', outstanding_after, update_modified=False)

        student = frappe.get_doc('Ex Student', self.ex_student)
        student.recompute_opening_balance()

    def _create_receipt_journal_entry(self):
        receivable_account, _opening = _get_ex_student_accounts(self.company)
        currency = _get_account_currency(self.received_in_account, self.company)

        je = frappe.new_doc('Journal Entry')
        # Cash Entry vs Bank Entry — mirrors the pattern used by Payment/Receipt Voucher
        acc_type = frappe.db.get_value('Account', self.received_in_account, 'account_type') or 'Bank'
        je.voucher_type = 'Cash Entry' if acc_type == 'Cash' else 'Bank Entry'
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or self.name
        je.cheque_date = self.reference_date or self.posting_date
        je.user_remark = self.remarks or _(
            'Ex-student fee receipt from {0}'
        ).format(self.student_name or self.ex_student)
        je.custom_source_voucher_doctype = 'Ex Student Receipt'
        je.custom_source_voucher = self.name

        # Debit: Received In Account (Bank/Cash)
        je.append('accounts', {
            'account': self.received_in_account,
            'account_currency': currency,
            'debit_in_account_currency': flt(self.amount),
            'credit_in_account_currency': 0,
        })
        # Credit: Ex-Students Receivable
        je.append('accounts', {
            'account': receivable_account,
            'account_currency': currency,
            'debit_in_account_currency': 0,
            'credit_in_account_currency': flt(self.amount),
        })

        _submit_doc(je)
        return je.name

    def _insert_ledger_entry(self, je_name):
        ledger = frappe.new_doc('Ex Student Ledger Entry')
        ledger.ex_student = self.ex_student
        ledger.company = self.company
        ledger.posting_date = self.posting_date
        ledger.debit = 0
        ledger.credit = flt(self.amount)
        ledger.voucher_type = 'Ex Student Receipt'
        ledger.voucher_no = self.name
        ledger.remarks = self.remarks or _('Fee receipt ({0})').format(self.mode_of_payment)
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
            WHERE voucher_type = 'Ex Student Receipt'
              AND voucher_no = %s
            ''',
            (self.name,),
        )

        self.db_set('is_posted', 0, update_modified=False)

        if self.ex_student and frappe.db.exists('Ex Student', self.ex_student):
            student = frappe.get_doc('Ex Student', self.ex_student)
            student.recompute_opening_balance()
