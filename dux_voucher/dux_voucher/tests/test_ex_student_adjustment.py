"""Unit tests for correcting ex-student openings (api/ex_student_api.py)
and for reconciling them with the GL (api/ex_student_recon.py).

These cover the pure parts: the Dr/Cr arithmetic of an adjustment, reading
a corrections CSV, matching its rows to students, and explaining a gap
between Ex-Students Receivable and the students' ledgers. The vouchers'
end-to-end posting is exercised on the dev site.
"""

import unittest

from dux_voucher.dux_voucher.api.ex_student_api import (
    _adjustment,
    _correct_opening_from_row,
    _match_student,
    _parse_amount,
    _signed,
    _split_signed,
    _student_index,
)
from dux_voucher.dux_voucher.api.ex_student_recon import _explain


class TestAdjustmentArithmetic(unittest.TestCase):

    def test_signed_and_split(self):
        self.assertEqual(_signed(500, 'Dr'), 500)
        self.assertEqual(_signed(500, 'Cr'), -500)
        self.assertEqual(_signed(-500, 'Dr'), 500)      # sign comes from Dr/Cr only
        self.assertEqual(_split_signed(1200.004), (1200.0, 'Dr'))
        self.assertEqual(_split_signed(-75.5), (75.5, 'Cr'))
        self.assertEqual(_split_signed(0.004), (0.0, 'Nil'))

    def test_typed_too_much(self):
        # Opening entered as 51,000 Dr; it should have been 15,000 Dr.
        self.assertEqual(_adjustment(51000, 15000, 'Dr'), (0.0, 36000))

    def test_typed_too_little(self):
        self.assertEqual(_adjustment(15000, 51000, 'Dr'), (36000, 0.0))

    def test_entered_on_the_wrong_side(self):
        # 2,500 entered as owed (Dr) but it was an advance (Cr): swing of 5,000.
        self.assertEqual(_adjustment(2500, 2500, 'Cr'), (0.0, 5000))

    def test_make_nil_and_start_from_nil(self):
        self.assertEqual(_adjustment(-8000, 0, 'Dr'), (8000, 0.0))
        self.assertEqual(_adjustment(0, 1250.5, 'Dr'), (1250.5, 0.0))

    def test_already_right_is_no_change(self):
        self.assertEqual(_adjustment(-4000, 4000, 'Cr'), (0.0, 0.0))

    def test_paise_do_not_leak(self):
        debit, credit = _adjustment(1000.1, 1000.3, 'Dr')
        self.assertAlmostEqual(debit, 0.2, places=2)
        self.assertEqual(credit, 0.0)


class TestCsvCells(unittest.TestCase):

    def test_parse_amount(self):
        self.assertEqual(_parse_amount('1,50,000'), (150000.0, None))
        self.assertEqual(_parse_amount(' 2500.50 '), (2500.5, None))
        self.assertEqual(_parse_amount(''), (None, None))
        self.assertEqual(_parse_amount(None), (None, None))
        self.assertIsNotNone(_parse_amount('Rs 500')[1])
        self.assertIsNotNone(_parse_amount('-200')[1])
        self.assertIsNotNone(_parse_amount('.')[1])

    def test_correct_opening_from_row(self):
        self.assertEqual(_correct_opening_from_row({'debit': '15000'}), (15000.0, 'Dr', None))
        self.assertEqual(_correct_opening_from_row({'debit': '', 'credit': '2,500'}), (2500.0, 'Cr', None))
        self.assertEqual(_correct_opening_from_row({'debit': '0'}), (0.0, 'Dr', None))     # nil
        self.assertEqual(_correct_opening_from_row({'credit': '0'}), (0.0, 'Dr', None))    # nil too
        self.assertIsNotNone(_correct_opening_from_row({'debit': '', 'credit': ''})[2])     # nothing given
        self.assertIsNotNone(_correct_opening_from_row({'debit': '10', 'credit': '5'})[2])  # both
        self.assertIsNotNone(_correct_opening_from_row({'debit': 'abc'})[2])


STUDENTS = [
    {'name': 'EX-STU-1', 'student_name': 'Ramesh Sharma', 'student_id': 'STU-001', 'is_disabled': 0},
    {'name': 'EX-STU-2', 'student_name': 'Priya Verma', 'student_id': 'STU-002', 'is_disabled': 0},
    {'name': 'EX-STU-3', 'student_name': 'Amit Patil', 'student_id': '', 'is_disabled': 0},
    {'name': 'EX-STU-4', 'student_name': 'Amit Patil', 'student_id': '', 'is_disabled': 0},
    {'name': 'EX-STU-5', 'student_name': 'Old Record', 'student_id': 'STU-009', 'is_disabled': 1},
    {'name': 'EX-STU-6', 'student_name': 'Old Record', 'student_id': '', 'is_disabled': 0},
]


class TestMatching(unittest.TestCase):

    def setUp(self):
        self.index = _student_index(STUDENTS)

    def test_by_record_id_first(self):
        self.assertEqual(_match_student({'ex_student': 'EX-STU-2', 'student_name': 'Amit Patil'}, self.index),
                         ('EX-STU-2', None))

    def test_by_student_id_then_name_case_insensitive(self):
        self.assertEqual(_match_student({'student_id': 'stu-001'}, self.index), ('EX-STU-1', None))
        self.assertEqual(_match_student({'student_name': '  priya verma '}, self.index), ('EX-STU-2', None))

    def test_ambiguous_name_is_refused(self):
        name, err = _match_student({'student_name': 'Amit Patil'}, self.index)
        self.assertIsNone(name)
        self.assertIn('EX-STU-3', err)
        self.assertIn('EX-STU-4', err)

    def test_disabled_students_are_never_matched(self):
        self.assertIsNotNone(_match_student({'ex_student': 'EX-STU-5'}, self.index)[1])
        self.assertIsNotNone(_match_student({'student_id': 'STU-009'}, self.index)[1])
        # the one enabled "Old Record" answers alone
        self.assertEqual(_match_student({'student_name': 'Old Record'}, self.index), ('EX-STU-6', None))

    def test_unknown_or_other_company(self):
        self.assertIsNotNone(_match_student({'ex_student': 'EX-STU-99'}, self.index)[1])
        self.assertIsNotNone(_match_student({'student_name': 'Nobody'}, self.index)[1])
        self.assertIsNotNone(_match_student({}, self.index)[1])


class TestReconcileExplain(unittest.TestCase):

    def test_items_add_up_to_the_gap(self):
        outside = [
            {'voucher_type': 'Journal Entry', 'voucher_no': 'JV-1', 'posting_date': None, 'amount': -11160},
            {'voucher_type': 'Journal Entry', 'voucher_no': 'JV-2', 'posting_date': None, 'amount': 0.001},
        ]
        gl = {('Ex Student Opening Batch', 'ESO-1'): 500000, ('Ex Student Receipt', 'ESR-1'): -35000}
        students = {('Ex Student Opening Batch', 'ESO-1'): 500000, ('Ex Student Receipt', 'ESR-1'): -35000,
                    ('Ex Student Receipt', 'ESR-2'): -35000}   # receipt cancelled, its row revived by hand
        items = _explain(outside, gl, students)
        self.assertEqual([(i['kind'], i['voucher_no'], i['amount']) for i in items],
                         [('outside', 'JV-1', -11160), ('mismatch', 'ESR-2', 35000)])
        total_gl = sum(o['amount'] for o in outside) + sum(gl.values())
        self.assertAlmostEqual(sum(i['amount'] for i in items), total_gl - sum(students.values()), places=2)

    def test_agreeing_books_explain_nothing(self):
        both = {('Ex Student Opening Adjustment', 'EOA-1'): -36000}
        self.assertEqual(_explain([], both, dict(both)), [])

    def test_net_nil_adjustment_has_no_journal_and_is_fine(self):
        # A move between two students posts rows that net to nil and no journal.
        self.assertEqual(_explain([], {}, {('Ex Student Opening Adjustment', 'EOA-2'): 0.0}), [])
