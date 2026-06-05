# Copyright (c) 2026, Dux Digitech and Contributors
# See license.txt

from frappe.tests import IntegrationTestCase


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []
IGNORE_TEST_RECORD_DEPENDENCIES = []


class IntegrationTestStudentFeeRefund(IntegrationTestCase):
    """
    Integration tests for StudentFeeRefund.

    Mirror of test_student_fee_receipt.py — left as a stub matching
    the receipt's structure so it can be filled in alongside the
    receipt's tests when those are written. Test cases planned:

      1. validate refuses if company / posting_date / student /
         paid_from_account / admission_year missing.
      2. validate refuses if total_amount <= 0 or any head amount <= 0.
      3. validate refuses if a head row's Course Fee Head doesn't
         belong to the student's course.
      4. validate refuses if paid_from_account is not Bank/Cash or
         company doesn't match.
      5. validate refuses if Student.company doesn't match.
      6. on_submit posts a JE: Dr Admission/Registration Fee,
         Cr paid_from_account, both legs equal to total_amount.
      7. on_cancel cancels the JE via _safe_cancel.
      8. amend a cancelled refund → new draft inserts cleanly (the
         insert() override clears backend_je + is_posted).
      9. Cancel the underlying JE directly → refund cancels via the
         on_journal_entry_cancel cascade hook.
     10. get_student_paid_summary returns the right sum + count.
    """

    pass
