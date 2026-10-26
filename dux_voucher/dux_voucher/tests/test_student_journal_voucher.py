"""Unit tests for students as ledger parties + Student Journal Voucher.

Covers the DB-cheap rules that decide what may post:

* which ledgers may sit opposite the student (:func:`_check_postable`) —
  in particular that income heads the RGI chart types "Cash" stay usable
  while real bank/cash accounts and party (Receivable/Payable) ledgers are
  refused;
* which side the student goes on per purpose;
* the Indian-FY window the bulk run uses to skip students already charged;
* the Journal Entry / Payment Entry guards and the balance helpers' blank
  inputs.

The full post → cancel-cascade → amend → bulk → migration flow posts real
Journal Entries in two companies and needs a set-up chart of accounts and
inter-company mappings; it is exercised by the scenario run on
``erp.jewonline.in`` (same policy as ``test_student_fee_receipt.py``).
"""

import unittest

import frappe

from dux_voucher.dux_voucher.api.student_ledger import (
    get_student_balance,
    get_student_balances,
    validate_journal_entry,
    validate_payment_entry,
)
from dux_voucher.dux_voucher.doctype.student_journal_voucher.student_journal_voucher import (
    CREDIT_PURPOSES,
    PURPOSES,
    TRANSFER_PURPOSES,
    StudentJournalVoucher,
    _check_postable,
    _indian_fy_bounds,
)


def _meta(**kw):
    base = {"name": "X - TEST", "is_group": 0, "disabled": 0, "account_type": "", "root_type": "Income"}
    base.update(kw)
    return frappe._dict(base)


class TestPostableLedgers(unittest.TestCase):

    def test_plain_income_ledger_allowed(self):
        _check_postable(_meta(), "Row 1")

    def test_income_head_typed_cash_allowed(self):
        # "Student ID Card Fine" on production: Income, account_type Cash.
        _check_postable(_meta(account_type="Cash", root_type="Income"), "Row 1")

    def test_real_cash_and_bank_refused(self):
        for t in ("Cash", "Bank"):
            with self.assertRaises(frappe.ValidationError):
                _check_postable(_meta(account_type=t, root_type="Asset"), "Row 1")

    def test_party_ledgers_refused(self):
        for t in ("Receivable", "Payable"):
            with self.assertRaises(frappe.ValidationError):
                _check_postable(_meta(account_type=t, root_type="Asset"), "Row 1")

    def test_group_and_disabled_refused(self):
        with self.assertRaises(frappe.ValidationError):
            _check_postable(_meta(is_group=1), "Row 1")
        with self.assertRaises(frappe.ValidationError):
            _check_postable(_meta(disabled=1), "Row 1")


class TestPurposes(unittest.TestCase):

    def test_student_side(self):
        for p in PURPOSES:
            doc = StudentJournalVoucher({"doctype": "Student Journal Voucher", "purpose": p})
            self.assertEqual(doc.student_side, "Cr" if p in CREDIT_PURPOSES else "Dr")

    def test_concession_credits_the_student(self):
        # The client's note had it the other way round; a concession reduces
        # what the student owes.
        self.assertIn("Concession", CREDIT_PURPOSES)

    def test_transfers_are_debits(self):
        for p in TRANSFER_PURPOSES:
            self.assertNotIn(p, CREDIT_PURPOSES)


class TestFinancialYear(unittest.TestCase):

    def test_bounds(self):
        self.assertEqual([str(d) for d in _indian_fy_bounds("2026-10-26")], ["2026-04-01", "2027-03-31"])
        self.assertEqual([str(d) for d in _indian_fy_bounds("2027-03-31")], ["2026-04-01", "2027-03-31"])
        self.assertEqual([str(d) for d in _indian_fy_bounds("2027-04-01")], ["2027-04-01", "2028-03-31"])


class TestGuards(unittest.TestCase):

    def test_payment_entry_refuses_student(self):
        with self.assertRaises(frappe.ValidationError):
            validate_payment_entry(frappe._dict(party_type="Student"))
        validate_payment_entry(frappe._dict(party_type="Customer"))   # untouched

    def test_journal_entry_without_students_untouched(self):
        doc = frappe._dict(company="Nope", accounts=[frappe._dict(party_type="Customer", party="C1", idx=1)])
        doc.get = lambda k, d=None: doc[k] if k in doc else d
        validate_journal_entry(doc)   # must not even resolve the student account

    def test_balance_blank_inputs(self):
        self.assertEqual(get_student_balance(None, "X"), 0.0)
        self.assertEqual(get_student_balance("X", None), 0.0)
        self.assertEqual(get_student_balances([], "X"), {})
