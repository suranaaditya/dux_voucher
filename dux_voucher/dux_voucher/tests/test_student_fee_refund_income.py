"""Unit tests for the retained-fee-as-income feature.

Covers the lightweight, DB-cheap parts:

* :func:`_student_provisional_balance` — blank-input guard and the
  zero result for a student with no receipts/refunds
* :func:`get_retained_income_account` — every resolver guard (unset,
  missing account, cross-company) plus the happy path

The full submit → book_income → JE → cancel-cascade flow posts real
Journal Entries against the Admission Fee and income accounts, which
needs a fully set-up CoA — that path is covered by the manual
integration smoke on ``erp.jewonline.in`` (mirroring the policy in
``test_student_fee_receipt.py``), not here.
"""

import unittest

import frappe

from dux_voucher.dux_voucher.api.student_fee import (
    _student_provisional_balance,
    get_retained_income_account,
)


SETTINGS = "Student Fee Settings"
FIELD = "retained_fee_income_account"


def _company():
    return frappe.get_all(
        "Company", filters={"is_group": 0}, fields=["name"], limit=1,
    )[0].name


def _leaf_account(company):
    """Any non-group, enabled account belonging to ``company`` — used as a
    stand-in income account for the happy-path test."""
    rows = frappe.get_all(
        "Account",
        filters={"company": company, "is_group": 0, "disabled": 0},
        fields=["name"], limit=1,
    )
    return rows[0].name if rows else None


# =====================================================================
# Provisional-balance helper
# =====================================================================

class TestProvisionalBalance(unittest.TestCase):

    def test_blank_inputs_return_zeros(self):
        for student, company in [(None, "X"), ("X", None), (None, None)]:
            bal = _student_provisional_balance(student, company)
            self.assertEqual(bal["paid"], 0.0)
            self.assertEqual(bal["refunded"], 0.0)
            self.assertEqual(bal["income_booked"], 0.0)
            self.assertEqual(bal["remaining"], 0.0)

    def test_unknown_student_returns_zeros(self):
        # A student id that doesn't exist has no receipts/refunds → all
        # sums COALESCE to zero, remaining is zero.
        bal = _student_provisional_balance(
            "PYTEST_NO_SUCH_STUDENT", _company())
        self.assertEqual(bal["remaining"], 0.0)
        self.assertEqual(bal["paid"], 0.0)


# =====================================================================
# Retained-income-account resolver
# =====================================================================

class TestRetainedIncomeAccountResolver(unittest.TestCase):

    def setUp(self):
        self.company = _company()
        self._orig = frappe.db.get_single_value(SETTINGS, FIELD)

    def tearDown(self):
        frappe.db.set_single_value(SETTINGS, FIELD, self._orig)
        frappe.db.commit()

    def test_convention_fallback_uses_per_company_name(self):
        # With the override blank, the resolver falls back to the
        # per-company convention account. Whether that account exists on
        # the test site isn't controllable here, so accept either outcome
        # — but the convention NAME must be used in both.
        frappe.db.set_single_value(SETTINGS, FIELD, None)
        abbr = frappe.get_cached_value("Company", self.company, "abbr")
        expected = f"Income From Admi Cancellation - {abbr}"
        try:
            self.assertEqual(get_retained_income_account(self.company), expected)
        except frappe.ValidationError as e:
            self.assertIn(expected, str(e))
            self.assertIn("Indirect Income", str(e))

    def test_missing_company_arg_throws(self):
        with self.assertRaises(frappe.ValidationError) as ctx:
            get_retained_income_account(None)
        self.assertIn("Company is required", str(ctx.exception))

    def test_override_nonexistent_account_throws(self):
        frappe.db.set_single_value(SETTINGS, FIELD, "No Such Acct - ZZZ")
        with self.assertRaises(frappe.ValidationError) as ctx:
            get_retained_income_account(self.company)
        self.assertIn("no longer exists", str(ctx.exception))

    def test_happy_path_returns_configured_account(self):
        acc = _leaf_account(self.company)
        if not acc:
            self.skipTest("no leaf account available on the test company")
        frappe.db.set_single_value(SETTINGS, FIELD, acc)
        self.assertEqual(get_retained_income_account(self.company), acc)

    def test_cross_company_account_throws(self):
        companies = frappe.get_all(
            "Company", filters={"is_group": 0}, fields=["name"], limit=2)
        if len(companies) < 2:
            self.skipTest("site has fewer than 2 companies")
        # Configure an account belonging to company[0], resolve for company[1].
        acc = _leaf_account(companies[0].name)
        if not acc:
            self.skipTest("no leaf account on the first company")
        frappe.db.set_single_value(SETTINGS, FIELD, acc)
        with self.assertRaises(frappe.ValidationError) as ctx:
            get_retained_income_account(companies[1].name)
        self.assertIn("belongs to", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
