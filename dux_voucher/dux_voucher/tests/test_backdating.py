"""Unit tests for the posting-date enforcement handler.

The handler is intentionally side-effect-free below the bypass-role
boundary — :func:`backdating._check` is pure logic and runs against
synthetic ``frappe._dict`` stand-ins for the doc and the settings
record. Tests of the bypass path mock the session-touching helper
:func:`backdating._user_has_bypass_role` and exercise the public
:func:`backdating.enforce` entry point.
"""

import unittest
from datetime import date
from unittest.mock import patch

import frappe

from dux_voucher.dux_voucher.api import backdating


# =====================================================================
# Helpers — synthetic settings / doc / rule
# =====================================================================

def _settings(enabled=1, enforce_for_amend=1, bypass_roles=None, rules=None):
    return frappe._dict({
        "enabled":           enabled,
        "enforce_for_amend": enforce_for_amend,
        "bypass_roles":      [frappe._dict({"role": r})
                               for r in (bypass_roles or [])],
        "rules":             [frappe._dict(r) for r in (rules or [])],
    })


def _rule(target_doctype="Payment Voucher",
           allow_backdating=0, max_days_back=0,
           allow_forward_dating=0, max_days_forward=0,
           date_field=""):
    return {
        "target_doctype":       target_doctype,
        "allow_backdating":     allow_backdating,
        "max_days_back":        max_days_back,
        "allow_forward_dating": allow_forward_dating,
        "max_days_forward":     max_days_forward,
        "date_field":           date_field,
    }


def _doc(doctype="Payment Voucher", posting_date=None,
          amended_from=None, **extras):
    d = frappe._dict({
        "doctype":      doctype,
        "posting_date": posting_date,
        "amended_from": amended_from,
    })
    d.update(extras)
    return d


TODAY = date(2026, 4, 30)


# =====================================================================
# Master toggle
# =====================================================================

class TestDisabled(unittest.TestCase):

    def test_disabled_is_silent(self):
        s = _settings(enabled=0,
                       rules=[_rule(allow_backdating=0)])
        # Way in the past, but enabled=0 → nothing happens.
        backdating._check(_doc(posting_date=date(2020, 1, 1)), s, TODAY)


# =====================================================================
# No matching rule
# =====================================================================

class TestNoRule(unittest.TestCase):

    def test_no_rule_for_doctype_silent(self):
        s = _settings(rules=[_rule(target_doctype="Some Other DocType",
                                     allow_backdating=0)])
        backdating._check(_doc(posting_date=date(2020, 1, 1)), s, TODAY)


# =====================================================================
# Backdating boundaries
# =====================================================================

class TestBackdating(unittest.TestCase):

    def test_same_day_passes(self):
        s = _settings(rules=[_rule()])
        backdating._check(_doc(posting_date=TODAY), s, TODAY)

    def test_backdate_blocked_when_disallowed(self):
        s = _settings(rules=[_rule(allow_backdating=0)])
        with self.assertRaises(frappe.ValidationError) as ctx:
            backdating._check(
                _doc(posting_date=date(2026, 4, 25)), s, TODAY)
        self.assertIn("not allowed", str(ctx.exception))

    def test_backdate_within_limit_passes(self):
        s = _settings(rules=[_rule(allow_backdating=1, max_days_back=7)])
        backdating._check(
            _doc(posting_date=date(2026, 4, 25)), s, TODAY)

    def test_backdate_at_exact_limit_passes(self):
        s = _settings(rules=[_rule(allow_backdating=1, max_days_back=7)])
        # 7 days back from 30 Apr → 23 Apr
        backdating._check(
            _doc(posting_date=date(2026, 4, 23)), s, TODAY)

    def test_backdate_one_day_over_limit_throws(self):
        s = _settings(rules=[_rule(allow_backdating=1, max_days_back=7)])
        with self.assertRaises(frappe.ValidationError) as ctx:
            backdating._check(
                _doc(posting_date=date(2026, 4, 22)), s, TODAY)
        self.assertIn("limited to 7", str(ctx.exception))


# =====================================================================
# Unlimited semantics — max_days_* == 0 means "no upper bound"
# =====================================================================

class TestUnlimited(unittest.TestCase):

    def test_backdate_with_zero_max_allows_far_past(self):
        # allow_backdating=1, max_days_back=0 → any past date passes.
        s = _settings(rules=[_rule(allow_backdating=1, max_days_back=0)])
        backdating._check(
            _doc(posting_date=date(1999, 1, 1)), s, TODAY)

    def test_forward_with_zero_max_allows_far_future(self):
        s = _settings(rules=[_rule(allow_forward_dating=1,
                                     max_days_forward=0)])
        backdating._check(
            _doc(posting_date=date(2099, 1, 1)), s, TODAY)


# =====================================================================
# Forward-dating boundaries
# =====================================================================

class TestForwardDating(unittest.TestCase):

    def test_forward_blocked_when_disallowed(self):
        s = _settings(rules=[_rule(allow_forward_dating=0)])
        with self.assertRaises(frappe.ValidationError) as ctx:
            backdating._check(
                _doc(posting_date=date(2026, 5, 5)), s, TODAY)
        self.assertIn("not allowed", str(ctx.exception))

    def test_forward_within_limit_passes(self):
        s = _settings(rules=[_rule(allow_forward_dating=1,
                                     max_days_forward=7)])
        backdating._check(
            _doc(posting_date=date(2026, 5, 5)), s, TODAY)

    def test_forward_at_exact_limit_passes(self):
        s = _settings(rules=[_rule(allow_forward_dating=1,
                                     max_days_forward=7)])
        backdating._check(
            _doc(posting_date=date(2026, 5, 7)), s, TODAY)

    def test_forward_one_day_over_limit_throws(self):
        s = _settings(rules=[_rule(allow_forward_dating=1,
                                     max_days_forward=7)])
        with self.assertRaises(frappe.ValidationError) as ctx:
            backdating._check(
                _doc(posting_date=date(2026, 5, 8)), s, TODAY)
        self.assertIn("limited to 7", str(ctx.exception))


# =====================================================================
# Amendment behaviour
# =====================================================================

class TestAmendment(unittest.TestCase):

    def test_amendment_with_enforce_off_passes(self):
        s = _settings(enforce_for_amend=0,
                       rules=[_rule(allow_backdating=0)])
        backdating._check(
            _doc(posting_date=date(2020, 1, 1), amended_from="ABC-001"),
            s, TODAY)

    def test_amendment_with_enforce_on_blocks(self):
        s = _settings(enforce_for_amend=1,
                       rules=[_rule(allow_backdating=0)])
        with self.assertRaises(frappe.ValidationError):
            backdating._check(
                _doc(posting_date=date(2020, 1, 1),
                     amended_from="ABC-001"),
                s, TODAY,
            )

    def test_non_amendment_unaffected_by_enforce_for_amend_flag(self):
        # enforce_for_amend=0 should not bypass the policy on a fresh
        # (non-amended) doc — it only skips the check on amendments.
        s = _settings(enforce_for_amend=0,
                       rules=[_rule(allow_backdating=0)])
        with self.assertRaises(frappe.ValidationError):
            backdating._check(
                _doc(posting_date=date(2020, 1, 1)),
                s, TODAY,
            )


# =====================================================================
# Per-rule date-field override (replaces the prior hardcoded map)
# =====================================================================

class TestDateFieldOverride(unittest.TestCase):

    def test_purchase_order_uses_transaction_date(self):
        # The rule row carries the override now; no hardcoded map.
        s = _settings(rules=[_rule(target_doctype="Purchase Order",
                                     allow_backdating=0,
                                     date_field="transaction_date")])
        doc = _doc(doctype="Purchase Order",
                    posting_date=None,
                    transaction_date=date(2020, 1, 1))
        with self.assertRaises(frappe.ValidationError):
            backdating._check(doc, s, TODAY)

    def test_purchase_order_ignores_posting_date_field(self):
        # Defensive: stale posting_date on a PO is not the field we
        # look up — the rule says transaction_date.
        s = _settings(rules=[_rule(target_doctype="Purchase Order",
                                     allow_backdating=0,
                                     date_field="transaction_date")])
        doc = _doc(doctype="Purchase Order",
                    posting_date=date(2020, 1, 1),
                    transaction_date=TODAY)
        backdating._check(doc, s, TODAY)

    def test_blank_date_field_falls_back_to_posting_date(self):
        # No date_field on the rule → handler defaults to posting_date.
        s = _settings(rules=[_rule(allow_backdating=0, date_field="")])
        with self.assertRaises(frappe.ValidationError):
            backdating._check(
                _doc(posting_date=date(2020, 1, 1)), s, TODAY)

    def test_arbitrary_custom_date_field(self):
        # Future doctypes can declare any fieldname they like; the
        # handler reads it via doc.get without code changes.
        s = _settings(rules=[_rule(target_doctype="Future DocType",
                                     allow_backdating=0,
                                     date_field="effective_from")])
        doc = _doc(doctype="Future DocType",
                    effective_from=date(2020, 1, 1))
        with self.assertRaises(frappe.ValidationError):
            backdating._check(doc, s, TODAY)

    def test_unknown_date_field_silently_skipped(self):
        # If the rule names a field that doesn't exist on the doc,
        # doc.get returns None → handler returns silently. This is
        # intentional: a typo on the Settings page mustn't break saves.
        s = _settings(rules=[_rule(allow_backdating=0,
                                     date_field="nonexistent_field")])
        backdating._check(
            _doc(posting_date=date(2020, 1, 1)), s, TODAY)


# =====================================================================
# Missing date — let upstream "required" validation handle it
# =====================================================================

class TestMissingDate(unittest.TestCase):

    def test_missing_posting_date_silent(self):
        s = _settings(rules=[_rule(allow_backdating=0)])
        backdating._check(_doc(posting_date=None), s, TODAY)


# =====================================================================
# Bypass-role short-circuit (touches session state — exercised via
# enforce() with mocks)
# =====================================================================

class TestBypassRole(unittest.TestCase):

    def test_bypass_role_short_circuits(self):
        s = _settings(bypass_roles=["Accounts Manager"],
                       rules=[_rule(allow_backdating=0)])
        doc = _doc(posting_date=date(2020, 1, 1))
        with patch.object(frappe, "get_cached_doc", return_value=s), \
             patch.object(backdating, "_user_has_bypass_role",
                            return_value=True):
            backdating.enforce(doc)  # should not throw

    def test_no_bypass_role_falls_through_to_check(self):
        s = _settings(bypass_roles=["Accounts Manager"],
                       rules=[_rule(allow_backdating=0)])
        doc = _doc(posting_date=date(2020, 1, 1))
        with patch.object(frappe, "get_cached_doc", return_value=s), \
             patch.object(backdating, "_user_has_bypass_role",
                            return_value=False):
            with self.assertRaises(frappe.ValidationError):
                backdating.enforce(doc)


# =====================================================================
# Public entry-point smoke (full path, master-disabled short-circuit)
# =====================================================================

class TestEnforceShortCircuits(unittest.TestCase):

    def test_enforce_returns_silently_when_disabled(self):
        s = _settings(enabled=0,
                       rules=[_rule(allow_backdating=0)])
        doc = _doc(posting_date=date(2020, 1, 1))
        with patch.object(frappe, "get_cached_doc", return_value=s):
            backdating.enforce(doc)


# =====================================================================
# Per-DocType wiring smoke
# =====================================================================

class TestStudentFeeReceiptCovered(unittest.TestCase):
    """Sanity that the new (8th) supported DocType is reached by the
    same enforcement logic as the rest. This isn't a separate
    code-path — the handler is generic over rule.target_doctype — but
    asserts that the eighth doctype name is recognised once it has a
    rule row."""

    def test_student_fee_receipt_backdating_blocks_when_disallowed(self):
        s = _settings(rules=[_rule(target_doctype="Student Fee Receipt",
                                     allow_backdating=0)])
        doc = _doc(doctype="Student Fee Receipt",
                    posting_date=date(2020, 1, 1))
        with self.assertRaises(frappe.ValidationError):
            backdating._check(doc, s, TODAY)

    def test_student_fee_receipt_within_limit_passes(self):
        s = _settings(rules=[_rule(target_doctype="Student Fee Receipt",
                                     allow_backdating=1, max_days_back=7)])
        doc = _doc(doctype="Student Fee Receipt",
                    posting_date=date(2026, 4, 25))   # 5 days back from TODAY
        backdating._check(doc, s, TODAY)


if __name__ == "__main__":
    unittest.main()
