"""Course Fee Head — a fee label valid for a specific Course.

E.g. 'Tuition', 'Hostel', 'Lab', 'Transport'. The label is purely a
presentation concept on the receipt — accounting only ever credits the
single 'Admission Fee / Registration' liability account regardless of
which heads were used to itemise the receipt.

Heads are scoped to a course (and transitively to a company) so the
receipt's head picker can be filtered tightly: an MBA student doesn't
see 'Lab Fee' if the MBA course doesn't have it.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class CourseFeeHead(Document):

    def validate(self):
        self._reject_duplicate()

    def _reject_duplicate(self):
        """Same head name cannot appear twice on the same course. Two
        different courses can share head names (both 'MBA' and 'BCom'
        having a 'Tuition' row is fine and expected)."""
        if not (self.head_name and self.course):
            return
        existing = frappe.db.get_value(
            "Course Fee Head",
            {
                "head_name": self.head_name,
                "course":    self.course,
                "name":      ["!=", self.name or "<new>"],
            },
            "name",
        )
        if existing:
            frappe.throw(
                _("Fee head '{0}' already exists for course {1} as {2}.")
                .format(self.head_name, self.course, existing)
            )
