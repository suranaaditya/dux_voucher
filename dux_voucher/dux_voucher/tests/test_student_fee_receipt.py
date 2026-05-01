"""Unit tests for Student Fee Receipt validation logic.

Submit / cancel flow exercises real Account doctype and Journal Entry
posting, which needs a fully set-up Admission Fee account and a
bank/cash account on the test company — too heavy for unit tests, so
that path is covered by the manual integration smoke on
``erp.jewonline.in`` (Phase 2 STOP-for-review checklist) rather than
here.

What we cover:

* :func:`current_admission_year` for various dates around the FY boundary
* validate-time rejections for every guard in the controller
* total_amount auto-recomputation from heads
"""

import unittest
from datetime import date

import frappe

from dux_voucher.dux_voucher.doctype.student_fee_receipt.student_fee_receipt import (
    current_admission_year,
)


TEST_PREFIX = "PYTEST_"


def _company():
    return frappe.get_all(
        "Company", filters={"is_group": 0}, fields=["name"], limit=1,
    )[0].name


def _make_course(name):
    return frappe.get_doc({
        "doctype":     "Course",
        "course_name": TEST_PREFIX + name,
    }).insert(ignore_permissions=True)


def _make_head(name, course):
    return frappe.get_doc({
        "doctype":   "Course Fee Head",
        "head_name": TEST_PREFIX + name,
        "course":    course.name,
    }).insert(ignore_permissions=True)


def _make_student(name, father, course, company=None):
    return frappe.get_doc({
        "doctype":      "Student",
        "student_name": TEST_PREFIX + name,
        "father_name":  TEST_PREFIX + father,
        "course":       course.name,
        "company":      company or _company(),
    }).insert(ignore_permissions=True)


def _new_receipt(student, heads_amounts=None, **overrides):
    """Build (but don't insert) a Student Fee Receipt with sensible
    defaults. Caller can override individual fields via ``overrides``."""
    doc = frappe.get_doc({
        "doctype":             "Student Fee Receipt",
        "company":             student.company,
        "posting_date":        date(2026, 5, 1),
        "student":             student.name,
        "received_in_account": overrides.pop(
            "received_in_account", "Cash - DUMMY"
        ),
        "heads": [
            {"head": h.name, "amount": amt}
            for h, amt in (heads_amounts or [])
        ],
    })
    for k, v in overrides.items():
        setattr(doc, k, v)
    return doc


def _cleanup():
    """Sweep test-prefixed records in dependency order."""
    # Receipts first (they hold links into the others); skipping in
    # case validate fails before insert (then nothing to clean).
    for dt, field in [
        ("Student Fee Receipt", "student_name"),
        ("Student",             "student_name"),
        ("Course Fee Head",     "head_name"),
        ("Course",              "course_name"),
    ]:
        for r in frappe.get_all(
            dt, filters={field: ["like", TEST_PREFIX + "%"]},
            fields=["name", "docstatus"],
        ):
            try:
                if r.get("docstatus") == 1:
                    d = frappe.get_doc(dt, r.name)
                    d.flags.ignore_permissions = True
                    d.cancel()
                frappe.delete_doc(dt, r.name, ignore_permissions=True,
                                    force=1)
            except Exception:
                pass
    frappe.db.commit()


# =====================================================================
# current_admission_year (pure helper)
# =====================================================================

class TestCurrentAdmissionYear(unittest.TestCase):

    def test_after_april_first(self):
        # 1-May-2026 → start of FY 2026-27
        self.assertEqual(
            current_admission_year(date(2026, 5, 1)),
            "FY 2026-27",
        )

    def test_on_april_first(self):
        # 1-Apr is exactly the boundary → counts as the new FY
        self.assertEqual(
            current_admission_year(date(2026, 4, 1)),
            "FY 2026-27",
        )

    def test_late_in_fiscal_year(self):
        # 15-Feb-2027 → still in FY 2026-27
        self.assertEqual(
            current_admission_year(date(2027, 2, 15)),
            "FY 2026-27",
        )

    def test_march_31_last_day_of_fy(self):
        self.assertEqual(
            current_admission_year(date(2027, 3, 31)),
            "FY 2026-27",
        )

    def test_january_falls_into_prior_fy(self):
        self.assertEqual(
            current_admission_year(date(2026, 1, 15)),
            "FY 2025-26",
        )


# =====================================================================
# Validate-time rejections
# =====================================================================

class TestReceiptValidation(unittest.TestCase):

    def setUp(self):
        _cleanup()
        self.course_mba  = _make_course("MBA")
        self.course_bcom = _make_course("BCom")
        self.head_tuition_mba = _make_head("Tuition", self.course_mba)
        self.head_hostel_mba  = _make_head("Hostel",  self.course_mba)
        self.head_tuition_bcom = _make_head("Tuition", self.course_bcom)
        self.student = _make_student("Aditya", "Mahesh", self.course_mba)

    def tearDown(self):
        _cleanup()

    # Note: these tests call the controller's individual validation
    # methods directly rather than going through ``insert()``, because
    # Frappe runs Link-existence checks on every reqd Link field
    # *before* invoking our ``validate``. Inserting with a non-
    # existent ``received_in_account`` therefore throws Frappe's own
    # error, never reaching our guard. Calling the granular methods
    # in isolation lets us assert on the specific message we emit
    # without standing up a full Account fixture for each case.

    # ── Field-level rejections ──────────────────────────────────────

    def test_missing_company_rejected(self):
        doc = _new_receipt(self.student,
                            [(self.head_tuition_mba, 10000)])
        doc.company = None
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc._validate_basic()
        self.assertIn("Company", str(ctx.exception))

    def test_missing_student_rejected(self):
        doc = _new_receipt(self.student,
                            [(self.head_tuition_mba, 10000)])
        doc.student = None
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc._validate_basic()
        self.assertIn("Student", str(ctx.exception))

    def test_no_heads_rejected(self):
        doc = _new_receipt(self.student, heads_amounts=[])
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc._validate_heads()
        self.assertIn("at least one fee head", str(ctx.exception))

    # ── Head ↔ student-course consistency ───────────────────────────

    def test_head_from_wrong_course_rejected(self):
        doc = _new_receipt(
            self.student,
            [(self.head_tuition_bcom, 5000)],   # student is MBA, head is BCom
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc._validate_heads()
        self.assertIn("not the student's course", str(ctx.exception))

    def test_zero_amount_row_rejected(self):
        doc = _new_receipt(
            self.student,
            [(self.head_tuition_mba, 0)],
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc._validate_heads()
        self.assertIn("greater than zero", str(ctx.exception))

    # ── Student ↔ receipt company consistency ───────────────────────

    def test_student_from_different_company_rejected(self):
        # Skip if site has < 2 companies.
        companies = frappe.get_all(
            "Company", filters={"is_group": 0}, fields=["name"], limit=2,
        )
        if len(companies) < 2:
            self.skipTest("site has fewer than 2 companies")
        student_a = _make_student(
            "Other", "Father", self.course_mba, company=companies[0].name,
        )
        doc = _new_receipt(
            student_a,
            [(self.head_tuition_mba, 1000)],
            company=companies[1].name,   # mismatch
        )
        with self.assertRaises(frappe.ValidationError) as ctx:
            doc._validate_student_consistency()
        self.assertIn("not", str(ctx.exception))

    def test_student_at_same_company_passes(self):
        """Sanity: validation succeeds when the student's company
        matches the receipt. Catches regressions where the consistency
        check accidentally throws on the happy path."""
        doc = _new_receipt(
            self.student,
            [(self.head_tuition_mba, 1000)],
        )
        # No exception should fire.
        doc._validate_student_consistency()

    # ── Total recomputation ─────────────────────────────────────────

    def test_total_amount_auto_recomputed_from_heads(self):
        # Caller leaves total_amount blank — controller should fill it.
        # We check via the in-memory doc rather than insert, since
        # insert here also requires a real bank/cash account.
        doc = _new_receipt(
            self.student,
            [
                (self.head_tuition_mba, 25000),
                (self.head_hostel_mba,  10000),
            ],
        )
        # Drive validate without touching DB-level account checks by
        # bypassing them via flag → just call the recomputation step.
        doc._compute_total()
        self.assertEqual(doc.total_amount, 35000)


if __name__ == "__main__":
    unittest.main()
