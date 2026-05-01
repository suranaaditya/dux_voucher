"""Course master — per-company list of programs offered.

A Course owns the set of fee heads (via the sibling ``Course Fee Head``
doctype) that are valid on a Student Fee Receipt for any student
enrolled in this course. Courses are expected to be a small list per
company (typically <20).

This module is purely a master record; no posting logic lives here.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class Course(Document):

    def validate(self):
        self._reject_duplicate()

    def _reject_duplicate(self):
        """A course name must be unique within a company. Different
        companies are free to have the same course (e.g. both JEWIPL
        and DD can offer 'MBA' independently)."""
        if not (self.course_name and self.company):
            return
        existing = frappe.db.get_value(
            "Course",
            {
                "course_name": self.course_name,
                "company":     self.company,
                "name":        ["!=", self.name or "<new>"],
            },
            "name",
        )
        if existing:
            frappe.throw(
                _("Course '{0}' already exists for {1} as {2}.")
                .format(self.course_name, self.company, existing)
            )
