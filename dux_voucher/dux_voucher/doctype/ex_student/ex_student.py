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
        """Recompute opening_balance from the parallel ledger."""
        total = frappe.db.sql(
            '''
            SELECT SUM(debit) - SUM(credit)
            FROM `tabEx Student Ledger Entry`
            WHERE ex_student = %s AND is_cancelled = 0
            ''',
            (self.name,),
        )
        value = flt(total[0][0]) if total and total[0][0] is not None else 0
        if flt(self.opening_balance) != value:
            frappe.db.set_value('Ex Student', self.name, 'opening_balance', value)
