"""Student master — incoming admissions only.

Scope is deliberately narrow: this doctype exists so the receipt
counter doesn't have to retype student names. The full lifecycle
(promotion, term-wise fees, transcripts, etc.) lives in a different
software entirely; this module only handles the *initial admission
fee* collection.

Course is a global doctype (shared across companies) but each Student
record carries its own ``company``, since a student is enrolled at
*one* institution at a time. Dedup is enforced at validate-time on
the (student_name, father_name, course, company) quadruple — the
same person can legitimately register at JEWIPL and DD without the
two records colliding.

Auto-name stays a clean ``STU-####`` so URLs and references survive
any combination of names with special characters; the human-readable
disambiguation is exposed via ``student_display`` which Frappe shows
everywhere (dropdowns, link previews, list view) because of the
``title_field`` setting on the doctype.
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document


# Indian mobile number regex: 10 digits, first digit in [6789].
# Apply *after* stripping any +91 / 91 prefix so users can paste
# numbers in either form without being told off.
_MOBILE_RE = re.compile(r"^[6-9]\d{9}$")


class Student(Document):

    def validate(self):
        self._compute_display()
        self._normalise_and_validate_mobile()
        self._reject_duplicate()

    # ── Display title ────────────────────────────────────────────────
    def _compute_display(self):
        """Compose the human-readable title shown in dropdowns and
        link previews. Format: ``Student Name — Father — Course``.

        Course's ``name`` is the course label itself (autoname is
        ``field:course_name``), so the rendered display reads cleanly
        as 'Aditya — Mahesh — MBA' without an extra DB lookup.
        """
        parts = [
            (self.student_name or "").strip(),
            (self.father_name  or "").strip(),
            (self.course       or "").strip(),
        ]
        self.student_display = "  —  ".join(p for p in parts if p)

    # ── Mobile normalisation + Indian-format validation ─────────────
    def _normalise_and_validate_mobile(self):
        """Strip optional +91 / 91 country-code prefix, drop spaces
        and dashes, then enforce the 10-digit Indian mobile format.

        Empty mobile is allowed (the field is optional). Invalid
        format throws — better to reject at counter than ship a
        receipt with a phone number we can't actually call back.
        """
        if not self.mobile:
            return
        cleaned = re.sub(r"[\s\-]", "", self.mobile.strip())
        if cleaned.startswith("+91"):
            cleaned = cleaned[3:]
        elif len(cleaned) == 12 and cleaned.startswith("91"):
            cleaned = cleaned[2:]
        if not _MOBILE_RE.match(cleaned):
            frappe.throw(
                _("Mobile must be a 10-digit Indian number starting with "
                  "6, 7, 8 or 9. Got: {0}").format(self.mobile)
            )
        # Persist the normalised 10-digit form so downstream code (SMS,
        # WhatsApp, exports) always sees one shape.
        self.mobile = cleaned

    # ── Dedup ────────────────────────────────────────────────────────
    def _reject_duplicate(self):
        """Same person registered twice for the same (course, company)
        is almost certainly a typo — block at validate time. Different
        course or different company for the same person is fine and
        stays as a separate Student record by design."""
        if not (self.student_name and self.father_name
                and self.course and self.company):
            return
        existing = frappe.db.get_value(
            "Student",
            {
                "student_name": self.student_name,
                "father_name":  self.father_name,
                "course":       self.course,
                "company":      self.company,
                "name":         ["!=", self.name or "<new>"],
            },
            ["name", "student_display"],
            as_dict=True,
        )
        if existing:
            frappe.throw(
                _("A student with this Name + Father + Course + Company "
                  "already exists: <strong>{0}</strong> ({1}).")
                .format(existing.student_display or existing.name,
                         existing.name)
            )
