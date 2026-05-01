"""Unit tests for the three new admission-fee master doctypes:

* :class:`Course`             — global, autoname = course_name
* :class:`Course Fee Head`    — attaches to a course; CFH-#### autoname
* :class:`Student`            — STU-#### autoname; dedup via validate

The tests run inside Frappe's test harness so they hit the real DB
rather than mocking it — masters are cheap to insert and clean up,
and the dedup logic depends on real ``frappe.db.get_value`` lookups
that are fiddly to mock convincingly.

Each test class creates its own scoped fixtures and rolls them back
in :meth:`tearDown`, so the tests can run in any order and leave no
trace on the site afterwards.
"""

import unittest

import frappe


# Local marker so the tearDown sweep only deletes records this module
# created, never anything pre-existing on the test site.
TEST_PREFIX = "PYTEST_"


def _company():
    """Return the first non-group company on the site. Tests need a
    real Company because Student.company is a hard Link constraint
    and we can't mock the FK relationship cheaply."""
    return frappe.get_all(
        "Company", filters={"is_group": 0}, fields=["name"], limit=1,
    )[0].name


def _make_course(course_name):
    return frappe.get_doc({
        "doctype":     "Course",
        "course_name": TEST_PREFIX + course_name,
    }).insert(ignore_permissions=True)


def _make_head(head_name, course):
    return frappe.get_doc({
        "doctype":   "Course Fee Head",
        "head_name": TEST_PREFIX + head_name,
        "course":    course.name,
    }).insert(ignore_permissions=True)


def _make_student(student_name, father_name, course, company=None,
                   mobile=None):
    doc = {
        "doctype":      "Student",
        "student_name": TEST_PREFIX + student_name,
        "father_name":  TEST_PREFIX + father_name,
        "course":       course.name,
        "company":      company or _company(),
    }
    if mobile is not None:
        doc["mobile"] = mobile
    return frappe.get_doc(doc).insert(ignore_permissions=True)


def _cleanup():
    """Best-effort sweep of any test-prefixed records left behind."""
    for dt, field in [
        ("Student",          "student_name"),
        ("Course Fee Head",  "head_name"),
        ("Course",           "course_name"),
    ]:
        for r in frappe.get_all(
            dt, filters={field: ["like", TEST_PREFIX + "%"]},
            fields=["name"],
        ):
            try:
                frappe.delete_doc(dt, r.name, ignore_permissions=True,
                                    force=1)
            except Exception:
                pass
    frappe.db.commit()


# =====================================================================
# Course (global, autoname = course_name)
# =====================================================================

class TestCourse(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_course_autonames_to_course_name(self):
        c = _make_course("MBA")
        # name == course_name (autoname is field:course_name)
        self.assertEqual(c.name, c.course_name)
        self.assertEqual(c.name, TEST_PREFIX + "MBA")

    def test_duplicate_course_name_rejected(self):
        _make_course("MBA")
        # Frappe raises DuplicateEntryError (subclass of ValidationError-ish)
        # when the unique-flagged primary key collides.
        with self.assertRaises(Exception) as ctx:
            _make_course("MBA")
        # Either DuplicateEntryError or ValidationError text — both
        # surface "already exists" or "Duplicate name" in the message.
        msg = str(ctx.exception)
        self.assertTrue("exist" in msg.lower() or "duplicate" in msg.lower(),
                          f"unexpected message: {msg!r}")


# =====================================================================
# Course Fee Head
# =====================================================================

class TestCourseFeeHead(unittest.TestCase):

    def setUp(self):
        _cleanup()
        self.course = _make_course("MBA")

    def tearDown(self):
        _cleanup()

    def test_head_can_be_created(self):
        h = _make_head("Tuition", self.course)
        self.assertTrue(h.name.startswith("CFH-"))
        self.assertEqual(h.course, self.course.name)

    def test_duplicate_head_in_same_course_rejected(self):
        _make_head("Tuition", self.course)
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_head("Tuition", self.course)
        self.assertIn("already exists", str(ctx.exception))

    def test_same_head_name_in_different_course_allowed(self):
        bcom = _make_course("BCom")
        _make_head("Tuition", self.course)
        h = _make_head("Tuition", bcom)
        self.assertEqual(h.course, bcom.name)


# =====================================================================
# Student
# =====================================================================

class TestStudent(unittest.TestCase):

    def setUp(self):
        _cleanup()
        self.course_mba  = _make_course("MBA")
        self.course_bcom = _make_course("BCom")

    def tearDown(self):
        _cleanup()

    def test_student_can_be_created(self):
        s = _make_student("Aditya", "Mahesh", self.course_mba)
        self.assertTrue(s.name.startswith("STU-"))
        # Display title composed at validate-time
        self.assertIn("Aditya",          s.student_display)
        self.assertIn("Mahesh",          s.student_display)
        self.assertIn(self.course_mba.name, s.student_display)

    def test_duplicate_student_same_quad_rejected(self):
        # Same (name, father, course, company) tuple → throws
        _make_student("Aditya", "Mahesh", self.course_mba)
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_student("Aditya", "Mahesh", self.course_mba)
        self.assertIn("already exists", str(ctx.exception))

    def test_same_student_different_course_allowed(self):
        _make_student("Aditya", "Mahesh", self.course_mba)
        s2 = _make_student("Aditya", "Mahesh", self.course_bcom)
        self.assertEqual(s2.course, self.course_bcom.name)

    def test_same_student_different_company_allowed(self):
        # Same person enrolling at two institutions → both accepted.
        # Skip if the site doesn't have two companies.
        companies = frappe.get_all(
            "Company", filters={"is_group": 0}, fields=["name"], limit=2,
        )
        if len(companies) < 2:
            self.skipTest("site has fewer than 2 companies")
        _make_student("Aditya", "Mahesh", self.course_mba,
                       company=companies[0].name)
        s2 = _make_student("Aditya", "Mahesh", self.course_mba,
                            company=companies[1].name)
        self.assertEqual(s2.company, companies[1].name)

    def test_same_name_different_father_allowed(self):
        _make_student("Aditya", "Mahesh", self.course_mba)
        s2 = _make_student("Aditya", "Suresh", self.course_mba)
        self.assertEqual(s2.father_name, TEST_PREFIX + "Suresh")

    def test_display_recomputes_on_save(self):
        s = _make_student("Aditya", "Mahesh", self.course_mba)
        old = s.student_display
        s.father_name = TEST_PREFIX + "Mahesh Kumar"
        s.save(ignore_permissions=True)
        self.assertNotEqual(s.student_display, old)
        self.assertIn("Mahesh Kumar", s.student_display)

    # ── Mobile validation ────────────────────────────────────────────

    def test_mobile_valid_10_digit(self):
        s = _make_student("Aditya", "Mahesh", self.course_mba,
                           mobile="9876543210")
        self.assertEqual(s.mobile, "9876543210")

    def test_mobile_with_plus_91_prefix_normalised(self):
        s = _make_student("Aditya", "Mahesh", self.course_mba,
                           mobile="+91 9876543210")
        self.assertEqual(s.mobile, "9876543210")

    def test_mobile_with_91_prefix_normalised(self):
        s = _make_student("Aditya", "Mahesh", self.course_mba,
                           mobile="919876543210")
        self.assertEqual(s.mobile, "9876543210")

    def test_mobile_with_dashes_and_spaces_normalised(self):
        s = _make_student("Aditya", "Mahesh", self.course_mba,
                           mobile="98765-43210")
        self.assertEqual(s.mobile, "9876543210")

    def test_mobile_starting_with_5_rejected(self):
        # Indian mobiles start with 6/7/8/9. 5xx would be a landline
        # short code, not a mobile.
        with self.assertRaises(frappe.ValidationError):
            _make_student("Aditya", "Mahesh", self.course_mba,
                           mobile="5876543210")

    def test_mobile_too_short_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            _make_student("Aditya", "Mahesh", self.course_mba,
                           mobile="987654321")

    def test_mobile_too_long_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            _make_student("Aditya", "Mahesh", self.course_mba,
                           mobile="98765432101")

    def test_mobile_optional(self):
        # Empty mobile is allowed — it's an optional field.
        s = _make_student("Aditya", "Mahesh", self.course_mba)
        self.assertFalse(s.mobile)


if __name__ == "__main__":
    unittest.main()
