import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dux_voucher.dux_voucher.api.utils import (
    _get_ex_student_accounts,
    _get_account_currency,
    _submit_doc,
    _safe_cancel,
)


class ExStudentWriteoff(Document):

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
        if not self.writeoff_account:
            frappe.throw(_('Write-Off Account is required'))
        if not self.reason:
            frappe.throw(_('Reason is required'))

        # Student must belong to the same company
        student_company = frappe.db.get_value('Ex Student', self.ex_student, 'company')
        if student_company != self.company:
            frappe.throw(_('Ex Student {0} belongs to company {1}, not {2}').format(
                self.ex_student, student_company, self.company))

        # Writeoff account: same company + expense root type
        acc_company, acc_root, acc_is_group = frappe.db.get_value(
            'Account', self.writeoff_account, ['company', 'root_type', 'is_group']
        ) or (None, None, None)
        if acc_company != self.company:
            frappe.throw(_('Write-Off Account {0} belongs to company {1}, not {2}').format(
                self.writeoff_account, acc_company, self.company))
        if acc_is_group:
            frappe.throw(_('Write-Off Account must be a ledger account, not a group'))
        if acc_root != 'Expense':
            frappe.throw(_('Write-Off Account must be an Expense type account (got root_type={0})').format(acc_root))

        # Ensure receivable account exists (via helper)
        _get_ex_student_accounts(self.company)

        # Capture current outstanding + check ceiling
        from dux_voucher.dux_voucher.api.ex_student_api import _current_outstanding
        outstanding = _current_outstanding(self.ex_student)
        self.current_outstanding = outstanding

        if outstanding <= 0.005:
            frappe.throw(_(
                'Ex Student {0} has no Dr outstanding ({1}). Nothing to write off.'
            ).format(self.student_name or self.ex_student, outstanding))

        if flt(self.amount) > outstanding + 0.005:
            frappe.throw(_(
                'Write-off amount ({0}) exceeds current Dr outstanding ({1}). '
                'You can write off up to the outstanding amount.'
            ).format(flt(self.amount), outstanding))

    # ------------------------------------------------------------------
    # On Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        from dux_voucher.dux_voucher.api.ex_student_api import _current_outstanding

        outstanding_before = _current_outstanding(self.ex_student)
        outstanding_after = outstanding_before - flt(self.amount)

        je_name = self._create_writeoff_journal_entry()
        self._insert_ledger_entry()

        self.db_set('backend_je', je_name, update_modified=False)
        self.db_set('is_posted', 1, update_modified=False)
        self.db_set('outstanding_before', outstanding_before, update_modified=False)
        self.db_set('outstanding_after', outstanding_after, update_modified=False)

        student = frappe.get_doc('Ex Student', self.ex_student)
        student.recompute_opening_balance()

    def _create_writeoff_journal_entry(self):
        receivable_account, _opening = _get_ex_student_accounts(self.company)
        currency = _get_account_currency(self.writeoff_account, self.company)

        je = frappe.new_doc('Journal Entry')
        # No money movement -- use plain Journal Entry type
        je.voucher_type = 'Journal Entry'
        je.company = self.company
        je.posting_date = self.posting_date
        je.user_remark = _('Ex-student write-off for {0}: {1}').format(
            self.student_name or self.ex_student, self.reason
        )
        je.custom_source_voucher_doctype = 'Ex Student Writeoff'
        je.custom_source_voucher = self.name

        # Debit: writeoff expense
        je.append('accounts', {
            'account': self.writeoff_account,
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

    def _insert_ledger_entry(self):
        ledger = frappe.new_doc('Ex Student Ledger Entry')
        ledger.ex_student = self.ex_student
        ledger.company = self.company
        ledger.posting_date = self.posting_date
        ledger.debit = 0
        ledger.credit = flt(self.amount)
        ledger.voucher_type = 'Ex Student Writeoff'
        ledger.voucher_no = self.name
        ledger.remarks = self.reason
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
            WHERE voucher_type = 'Ex Student Writeoff'
              AND voucher_no = %s
            ''',
            (self.name,),
        )
        self.db_set('is_posted', 0, update_modified=False)

        if self.ex_student and frappe.db.exists('Ex Student', self.ex_student):
            student = frappe.get_doc('Ex Student', self.ex_student)
            student.recompute_opening_balance()
