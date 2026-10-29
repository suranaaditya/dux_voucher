import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dux_voucher.dux_voucher.api.tb_aggregate import queue_month_refresh
from dux_voucher.dux_voucher.doctype.ex_student_ledger_entry.ex_student_ledger_entry import (
    delete_cancelled_ledger_rows,
    posting_ledger_rows,
    require_cancel_right,
)
from dux_voucher.dux_voucher.api.utils import (
    _get_ex_student_accounts,
    _get_account_currency,
    _submit_doc,
    _safe_cancel,
)


class ExStudentOpeningBatch(Document):

    def insert(self, *args, **kwargs):
        """Amend copies the cancelled journal into the new batch, and
        Frappe's link check then refuses to save it. Clear it first (same
        as Ex Student Refund / Student Fee Receipt)."""
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

        seen = set()
        total_debit = 0
        total_credit = 0

        for row in (self.students_table or []):
            if not row.ex_student:
                frappe.throw(_('Row {0}: Ex Student is required').format(row.idx))

            d = flt(row.debit_amount)
            c = flt(row.credit_amount)
            if d < 0 or c < 0:
                frappe.throw(_('Row {0}: Debit/Credit cannot be negative').format(row.idx))
            if d > 0 and c > 0:
                frappe.throw(_('Row {0}: A row cannot have both Debit and Credit amounts').format(row.idx))
            if d == 0 and c == 0:
                frappe.throw(_('Row {0}: Enter either Debit or Credit amount').format(row.idx))

            row_company = frappe.db.get_value('Ex Student', row.ex_student, 'company')
            if row_company != self.company:
                frappe.throw(_('Row {0}: Ex Student {1} belongs to company {2}, not {3}').format(
                    row.idx, row.ex_student, row_company, self.company))

            if row.ex_student in seen:
                frappe.throw(_('Row {0}: Ex Student {1} is repeated. Combine into one row.').format(
                    row.idx, row.ex_student))
            seen.add(row.ex_student)

            total_debit += d
            total_credit += c

        self.total_debit = total_debit
        self.total_credit = total_credit
        self.net_amount = total_debit - total_credit

        # Ensure accounts exist
        _get_ex_student_accounts(self.company)

    # ------------------------------------------------------------------
    # Before Submit
    # ------------------------------------------------------------------
    def before_submit(self):
        if not (self.students_table or []):
            frappe.throw(_('Please add at least one student row before submitting'))

    # ------------------------------------------------------------------
    # On Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        je_name = self._create_opening_journal_entry()
        self._insert_ledger_entries()

        self.db_set('backend_je', je_name, update_modified=False)
        self.db_set('is_posted', 1, update_modified=False)

        self._recompute_student_balances()
        if je_name:
            # Openings are back-dated: the nightly TB aggregate never reaches them.
            queue_month_refresh(self.company, self.posting_date)

    def _create_opening_journal_entry(self):
        receivable_account, opening_account = _get_ex_student_accounts(self.company)
        currency = _get_account_currency(receivable_account, self.company)

        net = flt(self.net_amount)
        if abs(net) < 0.005:
            # Gross-zero batch (total_debit == total_credit). Skip JE; ledger rows still recorded.
            return None

        je = frappe.new_doc('Journal Entry')
        je.voucher_type = 'Opening Entry'
        je.is_opening = 'Yes'
        je.company = self.company
        je.posting_date = self.posting_date
        je.user_remark = self.remarks or _('Ex-student opening balances - {0}').format(self.name)
        je.custom_source_voucher_doctype = 'Ex Student Opening Batch'
        je.custom_source_voucher = self.name

        if net > 0:
            # Net receivable
            je.append('accounts', {'account': receivable_account, 'account_currency': currency,
                                   'debit_in_account_currency': net, 'credit_in_account_currency': 0})
            je.append('accounts', {'account': opening_account, 'account_currency': currency,
                                   'debit_in_account_currency': 0, 'credit_in_account_currency': net})
        else:
            # Net advance/credit (students have credit balance)
            je.append('accounts', {'account': opening_account, 'account_currency': currency,
                                   'debit_in_account_currency': abs(net), 'credit_in_account_currency': 0})
            je.append('accounts', {'account': receivable_account, 'account_currency': currency,
                                   'debit_in_account_currency': 0, 'credit_in_account_currency': abs(net)})

        _submit_doc(je)
        return je.name

    def on_trash(self):
        # Frappe deletes only a cancelled voucher; its cancelled rows go with it.
        delete_cancelled_ledger_rows(self)

    def _insert_ledger_entries(self):
        for row in self.students_table:
            ledger = frappe.new_doc('Ex Student Ledger Entry')
            ledger.ex_student = row.ex_student
            ledger.company = self.company
            ledger.posting_date = self.posting_date
            ledger.debit = flt(row.debit_amount)
            ledger.credit = flt(row.credit_amount)
            ledger.voucher_type = 'Ex Student Opening Batch'
            ledger.voucher_no = self.name
            ledger.remarks = row.remarks or _('Opening balance')
            ledger.is_cancelled = 0
            with posting_ledger_rows(self):
                ledger.insert(ignore_permissions=True)

    # ------------------------------------------------------------------
    # On Cancel
    # ------------------------------------------------------------------
    def before_cancel(self):
        """An Opening Adjustment posts the difference between a student's
        opening and the correct figure. Cancelling the batch under it would
        leave that difference standing alone as the student's opening."""
        require_cancel_right(self)
        students = tuple({r.ex_student for r in self.students_table if r.ex_student})
        if not students:
            return
        # an adjustment submitting at this moment must wait, or be seen
        frappe.db.sql('SELECT name FROM `tabEx Student` WHERE name IN %s FOR UPDATE', (students,))
        live = frappe.db.sql_list(
            '''
            SELECT DISTINCT voucher_no FROM `tabEx Student Ledger Entry`
            WHERE voucher_type = 'Ex Student Opening Adjustment'
              AND is_cancelled = 0 AND ex_student IN %s
            ORDER BY voucher_no LOCK IN SHARE MODE
            ''',
            (students,),
        )
        if live:
            frappe.throw(_(
                'Students in this batch have their opening corrected by {0}. '
                'Cancel those adjustments first, or correct this batch with a new '
                'Opening Adjustment instead of cancelling it.'
            ).format(', '.join(live)), title=_('Opening Adjustments depend on this batch'))

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
        if self.backend_je:
            queue_month_refresh(self.company, self.posting_date)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _recompute_student_balances(self):
        for row in self.students_table:
            if row.ex_student and frappe.db.exists('Ex Student', row.ex_student):
                student = frappe.get_doc('Ex Student', row.ex_student)
                student.recompute_opening_balance()
