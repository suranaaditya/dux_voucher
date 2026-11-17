"""Unit tests for the guards on the Opening Batch CSV importer
(api/ex_student_api.py -> import_from_csv).

The importer once ran with no permission check at all. Any signed-in user
could fill any draft batch, create Ex Students in its company, and feed it
any file on the site by URL. These tests pin the guards:
- write on the batch;
- create on Ex Student for each student the sheet adds;
- only a file the caller has just uploaded for this batch.

They need a site context (frappe.throw, _()), so run them with
``bench --site <site> run-tests --module
dux_voucher.dux_voucher.tests.test_ex_student_batch_import``.
Nothing is written to the site. The batch, the file and the new student
are mocks, and every database call the importer makes is patched. Calls
for any other doctype go through to the real functions.
"""

import datetime
import unittest
from unittest.mock import MagicMock, patch

import frappe
from frappe.utils import add_to_date

from dux_voucher.dux_voucher.api import ex_student_api as api

BATCH = 'ESO-TEST-0001'
COMPANY = '_Test Ex Student Company'
FILE_URL = '/private/files/openings.csv'
NOW = datetime.datetime(2026, 11, 17, 12, 0, 0)
CSV = 'student_name,debit,credit\nRamesh Sharma,15000,\nPriya Verma,,2500\n'
EXISTING = {'Ramesh Sharma': 'EX-STU-1'}          # Priya Verma is new to the company


class TestBatchImportGuards(unittest.TestCase):

    def setUp(self):
        self.batch = MagicMock(doctype='Ex Student Opening Batch', docstatus=0, company=COMPANY)
        self.batch.name = BATCH
        self.file_doc = MagicMock()
        self.file_doc.get_content.return_value = CSV.encode('utf-8')
        self.files = [frappe._dict(name='FILE-1', creation=NOW,
                                   attached_to_doctype=None, attached_to_name=None)]
        self.file_filters = None
        self.new_student = MagicMock()
        self.new_student.name = 'EX-STU-NEW'
        self.new_student.has_permission.return_value = True

        get_doc, get_all, new_doc = frappe.get_doc, frappe.get_all, frappe.new_doc
        get_value = frappe.local.db.get_value

        def fake_get_doc(doctype, *args, **kwargs):
            if doctype == 'Ex Student Opening Batch':
                return self.batch
            if doctype == 'File':
                return self.file_doc
            return get_doc(doctype, *args, **kwargs)

        def fake_get_all(doctype, *args, **kwargs):
            if doctype != 'File':
                return get_all(doctype, *args, **kwargs)
            self.file_filters = kwargs.get('filters')
            return list(self.files)

        def fake_new_doc(doctype, *args, **kwargs):
            return self.new_student if doctype == 'Ex Student' else new_doc(doctype, *args, **kwargs)

        def fake_get_value(doctype, filters=None, *args, **kwargs):
            if doctype == 'Ex Student' and isinstance(filters, dict) and filters.get('company') == COMPANY:
                return EXISTING.get(filters.get('student_name'))
            return get_value(doctype, filters, *args, **kwargs)

        self.commit = MagicMock()
        for target, attr, new in (
            (frappe, 'get_doc', fake_get_doc),
            (frappe, 'get_all', fake_get_all),
            (frappe, 'new_doc', fake_new_doc),
            (frappe.local.db, 'get_value', fake_get_value),
            (frappe.local.db, 'commit', self.commit),
            (api, 'now_datetime', lambda: NOW),
        ):
            patcher = patch.object(target, attr, new)
            patcher.start()
            self.addCleanup(patcher.stop)

    def assert_nothing_imported(self):
        self.file_doc.get_content.assert_not_called()
        self.batch.append.assert_not_called()
        self.batch.save.assert_not_called()
        self.new_student.insert.assert_not_called()
        self.commit.assert_not_called()

    def test_needs_write_on_the_batch(self):
        self.batch.check_permission.side_effect = frappe.PermissionError
        with self.assertRaises(frappe.PermissionError):
            api.import_from_csv(BATCH, FILE_URL)
        self.batch.check_permission.assert_called_once_with('write')
        self.assertIsNone(self.file_filters)           # the file is not even looked up
        self.assert_nothing_imported()

    def test_refuses_a_file_the_caller_did_not_upload(self):
        self.files = []                                # no file of theirs at that URL
        with self.assertRaises(frappe.ValidationError):
            api.import_from_csv(BATCH, FILE_URL)
        self.assertEqual(self.file_filters, {'file_url': FILE_URL, 'owner': frappe.session.user})
        self.assert_nothing_imported()

    def test_refuses_an_old_upload(self):
        self.files[0].creation = add_to_date(NOW, hours=-2)
        with self.assertRaises(frappe.ValidationError):
            api.import_from_csv(BATCH, FILE_URL)
        self.assertIsNotNone(self.file_filters)        # refused by the upload check, not a missing file
        self.assert_nothing_imported()

    def test_refuses_a_file_attached_to_another_document(self):
        self.files[0].update(attached_to_doctype='Purchase Invoice', attached_to_name='PINV-0001')
        with self.assertRaises(frappe.ValidationError):
            api.import_from_csv(BATCH, FILE_URL)
        self.assertIsNotNone(self.file_filters)
        self.assert_nothing_imported()

    def test_imports_a_fresh_upload_and_keeps_it_with_the_batch(self):
        out = api.import_from_csv(BATCH, FILE_URL)
        self.assertEqual(out, {'created': 1, 'appended': 2, 'errors': []})
        self.assertEqual([c.args[1]['ex_student'] for c in self.batch.append.call_args_list],
                         ['EX-STU-1', 'EX-STU-NEW'])
        self.new_student.has_permission.assert_called_once_with('create')
        self.new_student.insert.assert_called_once_with()     # with the caller's permissions
        self.batch.save.assert_called_once_with()             # likewise
        self.file_doc.db_set.assert_called_once_with(
            {'attached_to_doctype': 'Ex Student Opening Batch', 'attached_to_name': BATCH})

    def test_accepts_a_file_already_attached_to_this_batch(self):
        self.files[0].update(attached_to_doctype='Ex Student Opening Batch', attached_to_name=BATCH)
        out = api.import_from_csv(BATCH, FILE_URL)
        self.assertEqual(out['appended'], 2)
        self.file_doc.db_set.assert_not_called()

    def test_a_new_student_needs_create_permission(self):
        self.new_student.has_permission.return_value = False
        out = api.import_from_csv(BATCH, FILE_URL)
        self.assertEqual((out['created'], out['appended']), (0, 1))   # the existing student still goes in
        self.assertEqual(len(out['errors']), 1)
        self.assertTrue(out['errors'][0].startswith('Row 3: '))
        self.assertIn('Priya Verma', out['errors'][0])
        self.new_student.insert.assert_not_called()
        self.assertEqual([c.args[1]['ex_student'] for c in self.batch.append.call_args_list], ['EX-STU-1'])
        self.batch.save.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
