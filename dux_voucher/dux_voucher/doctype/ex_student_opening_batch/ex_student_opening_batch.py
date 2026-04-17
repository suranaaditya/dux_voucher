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


class ExStudentOpeningBatch(Document):

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------
    def validate(self):
        if not self.company:
            frappe.throw(_('Company is required'))
        if not self.posting_date:
            frappe.throw(_('Posting Date is required'))
        seen = set()
        total = 0
        for row in self.students_table:
            if not row.ex_student:
                frappe.throw(_('Row {0}: Ex Student is required').format(row.idx))
            if flt(row.amount) <= 0:
                frappe.throw(_('Row {0}: Amount must be greater than zero').format(row.idx))

            row_company = frappe.db.get_value('Ex Student', row.ex_student, 'company')
            if row_company != self.company:
                frappe.throw(_(
                    'Row {0}: Ex Student {1} belongs to company {2}, not {3}'
                ).format(row.idx, row.ex_student, row_company, self.company))

            if row.ex_student in seen:
                frappe.throw(_(
                    'Row {0}: Ex Student {1} is repeated. Combine the amounts into one row.'
                ).format(row.idx, row.ex_student))
            seen.add(row.ex_student)
            total += flt(row.amount)

        self.total_amount = total

        # Ensure both accounts exist in the CoA (will throw if missing)
        _get_ex_student_accounts(self.company)

    # ------------------------------------------------------------------
    # Before Submit — block submission of an empty batch
    # ------------------------------------------------------------------
    def before_submit(self):
        if not self.students_table:
            frappe.throw(_('Please add at least one student row before submitting'))

    # ------------------------------------------------------------------
    # On Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        je_name = self._create_opening_journal_entry()
        self._insert_ledger_entries(je_name)

        self.db_set('backend_je', je_name, update_modified=False)
        self.db_set('is_posted', 1, update_modified=False)

        self._recompute_student_balances()

    def _create_opening_journal_entry(self):
        receivable_account, opening_account = _get_ex_student_accounts(self.company)
        currency = _get_account_currency(receivable_account, self.company)

        je = frappe.new_doc('Journal Entry')
        je.voucher_type = 'Opening Entry'
        je.is_opening = 'Yes'
        je.company = self.company
        je.posting_date = self.posting_date
        je.user_remark = self.remarks or _(
            'Ex-student opening balances — {0}'
        ).format(self.name)
        je.custom_source_voucher_doctype = 'Ex Student Opening Batch'
        je.custom_source_voucher = self.name

        je.append('accounts', {
            'account': receivable_account,
            'account_currency': currency,
            'debit_in_account_currency': flt(self.total_amount),
            'credit_in_account_currency': 0,
        })
        je.append('accounts', {
            'account': opening_account,
            'account_currency': currency,
            'debit_in_account_currency': 0,
            'credit_in_account_currency': flt(self.total_amount),
        })

        _submit_doc(je)
        return je.name

    def _insert_ledger_entries(self, je_name):
        for row in self.students_table:
            ledger = frappe.new_doc('Ex Student Ledger Entry')
            ledger.ex_student = row.ex_student
            ledger.company = self.company
            ledger.posting_date = self.posting_date
            ledger.debit = flt(row.amount)
            ledger.credit = 0
            ledger.voucher_type = 'Ex Student Opening Batch'
            ledger.voucher_no = self.name
            ledger.remarks = row.remarks or _('Opening balance')
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
            WHERE voucher_type = 'Ex Student Opening Batch'
              AND voucher_no = %s
            ''',
            (self.name,),
        )

        self.db_set('is_posted', 0, update_modified=False)

        self._recompute_student_balances()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _recompute_student_balances(self):
        for row in self.students_table:
            student = frappe.get_doc('Ex Student', row.ex_student)
            student.recompute_opening_balance()
