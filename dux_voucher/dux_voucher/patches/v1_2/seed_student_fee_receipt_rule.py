"""Add the Student Fee Receipt rule row to existing Dux Backdating
Settings records.

The v1_0 seed patch ran on already-deployed sites with the original
seven supported doctypes. When ``Student Fee Receipt`` was added as
the eighth, those sites' Settings rows ended up missing the new rule
— the controller's ``before_save`` safety-net only fires on save,
so until the user manually saved Settings, the new doctype had no
matching rule and the validate hook would silently skip it (no rule
= no enforcement).

This patch adds the missing rule with policy-default values
(disallow back- and forward-dating, both day caps zero). Idempotent —
re-running is a no-op once the row exists.
"""

import frappe

from dux_voucher.dux_voucher.doctype.dux_backdating_settings.dux_backdating_settings import (
    default_rule,
)


TARGET = "Student Fee Receipt"


def execute():
    settings = frappe.get_single("Dux Backdating Settings")
    if any(r.target_doctype == TARGET for r in (settings.rules or [])):
        print(f"[dux_voucher] seed_student_fee_receipt_rule: "
              f"already present, no-op")
        return

    settings.append("rules", default_rule(TARGET))
    settings.flags.ignore_permissions = True
    settings.save()
    frappe.db.commit()
    print(f"[dux_voucher] seed_student_fee_receipt_rule: "
          f"added rule for {TARGET}")
