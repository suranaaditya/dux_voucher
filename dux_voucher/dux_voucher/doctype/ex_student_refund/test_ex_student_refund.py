# Copyright (c) 2026, Dux Digitech and Contributors
# See license.txt

from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestExStudentRefund(IntegrationTestCase):
    """
    Integration tests for ExStudentRefund.

    Mirror of test_ex_student_receipt.py — left as a stub matching the
    receipt's structure so it can be filled in alongside the receipt's
    tests when those are written.
    """

    pass
