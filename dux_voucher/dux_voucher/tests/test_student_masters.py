"""Unit tests for the three new admission-fee master doctypes:

* :class:`Course`
* :class:`Course Fee Head`
* :class:`Student`

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


# A local marker so the tearDown sweep only deletes records this
# module created, never anything pre-existing on the test site.
TEST_PREFIX = "PYTEST_"


def _company():
    """Return the first non-group company on the site. Tests need
    a real Company because Course.company is a hard Link constraint
    and we can't mock the FK relationship cheaply."""
    return frappe.get_all(
        "Company", filters={"is_group": 0}, fields=["name"],
        limit_page_length=1,
    )[0].name


def _make_course(course_name, company=None):
    return frappe.get_doc({
        "doctype":     "Course",
        "course_name": TEST_PREFIX + course_name,
        "company":     company or _company(),
    }).insert(ignore_permissions=True)


def _make_head(head_name, course):
    return frappe.get_doc({
        "doctype":   "Course Fee Head",
        "head_name": TEST_PREFIX + head_name,
        "course":    course.name,
    }).insert(ignore_permissions=True)


def _make_student(student_name, father_name, course):
    return frappe.get_doc({
        "doctype":      "Student",
        "student_name": TEST_PREFIX + student_name,
        "father_name":  TEST_PREFIX + father_name,
        "course":       course.name,
    }).insert(ignore_permissions=True)


def _cleanup():
    """Best-effort sweep of any test-prefixed records left behind."""
    # Delete in dependency order: Student → Course Fee Head → Course
    for dt, field in [
        ("Student",          "student_name"),
        ("Course Fee Head",  "head_name"),
        ("Course",           "course_name"),
    ]:
        for r in frappe.get_all(
            dt,
            filters={field: ["like", TEST_PREFIX + "%"]},
            fields=["name"],
        ):
            try:
                frappe.delete_doc(dt, r.name, ignore_permissions=True,
                                    force=1)
            except Exception:
                # If delete fails (e.g. linked from a real record) we
                # don't want one stale row to break subsequent tests.
                # Frappe's test harness rolls back the transaction
                # anyway so this is mostly belt-and-braces.
                pass
    frappe.db.commit()


# =====================================================================
# Course
# =====================================================================

class TestCourse(unittest.TestCase):

    def setUp(self):
        _cleanup()

    def tearDown(self):
        _cleanup()

    def test_course_can_be_created(self):
        c = _make_course("MBA")
        self.assertTrue(c.name.startswith("CRS-"))
        self.assertEqual(c.course_name, TEST_PREFIX + "MBA")

    def test_duplicate_course_name_in_same_company_rejected(self):
        _make_course("MBA")
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_course("MBA")
        self.assertIn("already exists", str(ctx.exception))

    def test_same_course_name_in_different_company_allowed(self):
        # If the site has only one company, this case is degenerate;
        # skip rather than fail to keep the test resilient.
        companies = frappe.get_all(
            "Company", filters={"is_group": 0}, fields=["name"],
            limit_page_length=2,
        )
        if len(companies) < 2:
            self.skipTest("site has fewer than 2 companies")
        _make_course("MBA", company=companies[0].name)
        # Same course_name, different company → allowed
        _make_course("MBA", company=companies[1].name)


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
        # company must auto-fetch from the course
        self.assertEqual(h.company, self.course.company)

    def test_duplicate_head_in_same_course_rejected(self):
        _make_head("Tuition", self.course)
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_head("Tuition", self.course)
        self.assertIn("already exists", str(ctx.exception))

    def test_same_head_name_in_different_course_allowed(self):
        bcom = _make_course("BCom")
        _make_head("Tuition", self.course)
        # Same head name on a different course → fine; both courses
        # legitimately have a 'Tuition' fee head.
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
        self.assertIn("Aditya",  s.student_display)
        self.assertIn("Mahesh",  s.student_display)
        self.assertIn(self.course_mba.name, s.student_display)
        # company auto-fetched from course
        self.assertEqual(s.company, self.course_mba.company)

    def test_duplicate_student_same_name_father_course_rejected(self):
        _make_student("Aditya", "Mahesh", self.course_mba)
        with self.assertRaises(frappe.ValidationError) as ctx:
            _make_student("Aditya", "Mahesh", self.course_mba)
        # Error message should mention the existing student so the
        # counter operator knows where the conflict is, not just that
        # one exists.
        msg = str(ctx.exception)
        self.assertIn("already exists", msg)

    def test_same_student_different_course_allowed(self):
        _make_student("Aditya", "Mahesh", self.course_mba)
        # Same person enrolling in a second course → ok, separate row.
        s2 = _make_student("Aditya", "Mahesh", self.course_bcom)
        self.assertEqual(s2.course, self.course_bcom.name)

    def test_same_name_different_father_allowed(self):
        # Two unrelated students who share a first name but have
        # different fathers must both be accepted.
        _make_student("Aditya", "Mahesh", self.course_mba)
        s2 = _make_student("Aditya", "Suresh", self.course_mba)
        self.assertEqual(s2.father_name, TEST_PREFIX + "Suresh")

    def test_display_recomputes_on_save(self):
        s = _make_student("Aditya", "Mahesh", self.course_mba)
        old_display = s.student_display
        s.father_name = TEST_PREFIX + "Mahesh Kumar"
        s.save(ignore_permissions=True)
        self.assertNotEqual(s.student_display, old_display)
        self.assertIn("Mahesh Kumar", s.student_display)


if __name__ == "__main__":
    unittest.main()
