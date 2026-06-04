"""Add the Ex Student Refund rule row to existing Dux Backdating
Settings records.

The v1_0 seed patch ran on already-deployed sites with the original
seven supported doctypes; v1_2 added Student Fee Receipt as the
eighth. Ex Student Refund makes nine. Existing sites' Settings rows
lack the new rule until either (a) someone saves Settings (the
controller's ``before_save`` safety-net would seed it), or (b) this
patch runs. The ``validate`` hook treats a missing rule as
"unenforced", so without the row the policy silently skips Refunds.

This patch adds the missing rule with policy-default values
(disallow back- and forward-dating, both day caps zero). Idempotent —
re-running is a no-op once the row exists.
"""

import frappe

from dux_voucher.dux_voucher.doctype.dux_backdating_settings.dux_backdating_settings import (
    default_rule,
)


TARGET = "Ex Student Refund"


def execute():
    settings = frappe.get_single("Dux Backdating Settings")
    if any(r.target_doctype == TARGET for r in (settings.rules or [])):
        print(f"[dux_voucher] seed_ex_student_refund_rule: "
              f"already present, no-op")
        return

    settings.append("rules", default_rule(TARGET))
    settings.flags.ignore_permissions = True
    settings.save()
    frappe.db.commit()
    print(f"[dux_voucher] seed_ex_student_refund_rule: "
          f"added rule for {TARGET}")
