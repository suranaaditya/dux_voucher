import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class ExStudent(Document):

    def validate(self):
        self._validate_unique_in_company()

    def _validate_unique_in_company(self):
        if not self.student_name or not self.company:
            return
        existing = frappe.db.get_value(
            'Ex Student',
            {
                'student_name': self.student_name,
                'company': self.company,
                'name': ('!=', self.name or ''),
                'is_disabled': 0,
            },
            'name',
        )
        if existing:
            frappe.throw(_(
                'An Ex Student named {0} already exists for {1} ({2}). '
                'Disable or rename the existing record first.'
            ).format(self.student_name, self.company, existing))

    def recompute_opening_balance(self):
        """Recompute signed balance + balance_type from the parallel ledger."""
        row = frappe.db.sql(
            '''
            SELECT SUM(debit) - SUM(credit)
            FROM `tabEx Student Ledger Entry`
            WHERE ex_student = %s AND is_cancelled = 0
            ''',
            (self.name,),
        )
        signed = flt(row[0][0]) if row and row[0][0] is not None else 0

        if signed > 0.005:
            balance_type = 'Dr'
        elif signed < -0.005:
            balance_type = 'Cr'
        else:
            balance_type = 'Nil'

        if flt(self.opening_balance) != signed or (self.balance_type or 'Nil') != balance_type:
            frappe.db.set_value(
                'Ex Student', self.name,
                {'opening_balance': signed, 'balance_type': balance_type},
                update_modified=False,
            )
