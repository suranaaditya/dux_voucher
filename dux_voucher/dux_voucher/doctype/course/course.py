"""Course master — globally shared list of programs.

A Course is **not company-scoped** — the same course (e.g. 'MBA')
exists once and can be referenced by students enrolled at any
institution. Course Fee Heads (sibling doctype) attach to the course,
so the head list is also shared across companies.

Auto-name is the course name itself (`autoname: field:course_name`),
which makes Link fields display the course as 'MBA' rather than a
synthetic CRS-#### id. The `unique` flag on `course_name` enforces
single-row-per-name at the DB level — no controller-side dedup
needed.
"""

import frappe
from frappe.model.document import Document


class Course(Document):
    pass
