"""Student master — incoming admissions only.

Scope is deliberately narrow: this doctype exists so the receipt
counter doesn't have to retype student names. The full lifecycle
(promotion, term-wise fees, transcripts, etc.) lives in a different
software entirely; this module only handles the *initial admission
fee* collection.

Dedup is enforced at validate-time on the (student_name, father_name,
course) triple. Auto-name stays a clean ``STU-####`` so URLs and
references survive any combination of names with special characters;
the human-readable disambiguation is exposed via ``student_display``
which Frappe shows everywhere (dropdowns, link previews, list view)
because of the ``title_field`` setting on the doctype.
"""

import frappe
from frappe import _
from frappe.model.document import Document


class Student(Document):

    def validate(self):
        self._compute_display()
        self._reject_duplicate()

    # ── Display title ────────────────────────────────────────────────
    def _compute_display(self):
        """Compose the human-readable title shown in dropdowns and
        link previews. Format: ``Student Name — Father — Course``.

        Recomputed on every save so renaming a Course (or fixing a
        typo in father_name) propagates without manual cleanup. The
        em-dash is intentional — visually cleaner than a hyphen and
        less likely to collide with any value the user has typed.
        """
        parts = [
            (self.student_name or "").strip(),
            (self.father_name  or "").strip(),
            (self.course       or "").strip(),
        ]
        self.student_display = "  —  ".join(p for p in parts if p)

    # ── Dedup ────────────────────────────────────────────────────────
    def _reject_duplicate(self):
        """Same person registered twice for the same course is almost
        certainly a typo — block at validate time. Different course
        for the same person is fine (someone re-enrolling) and stays
        as a separate Student record by design."""
        if not (self.student_name and self.father_name and self.course):
            return
        existing = frappe.db.get_value(
            "Student",
            {
                "student_name": self.student_name,
                "father_name":  self.father_name,
                "course":       self.course,
                "name":         ["!=", self.name or "<new>"],
            },
            ["name", "student_display"],
            as_dict=True,
        )
        if existing:
            frappe.throw(
                _("A student with this Name + Father + Course already "
                  "exists: <strong>{0}</strong> ({1}).")
                .format(existing.student_display or existing.name,
                         existing.name)
            )
