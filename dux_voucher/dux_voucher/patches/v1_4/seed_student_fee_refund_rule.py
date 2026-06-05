"""Add the Student Fee Refund rule row to existing Dux Backdating
Settings records.

Same shape as the v1_2 (Student Fee Receipt) and v1_3 (Ex Student
Refund) patches. Idempotent: a re-run is a no-op once the row exists.

Why a patch instead of relying on the controller's ``before_save``
safety net: existing sites already have a saved Settings row, so the
new rule wouldn't appear until someone manually re-saved Settings.
The ``validate`` hook treats a missing rule as "unenforced", so
without this patch the policy silently skips refunds until then.
"""

import frappe

from dux_voucher.dux_voucher.doctype.dux_backdating_settings.dux_backdating_settings import (
    default_rule,
)


TARGET = "Student Fee Refund"


def execute():
    settings = frappe.get_single("Dux Backdating Settings")
    if any(r.target_doctype == TARGET for r in (settings.rules or [])):
        print(f"[dux_voucher] seed_student_fee_refund_rule: "
              f"already present, no-op")
        return

    settings.append("rules", default_rule(TARGET))
    settings.flags.ignore_permissions = True
    settings.save()
    frappe.db.commit()
    print(f"[dux_voucher] seed_student_fee_refund_rule: "
          f"added rule for {TARGET}")
