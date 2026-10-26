"""Add the Student Journal Voucher rule row to existing Dux Backdating
Settings records — the 11th controlled doctype.

Same shape as the v1_2 / v1_3 / v1_4 rule patches. Idempotent: a re-run is
a no-op once the row exists.
"""

import frappe

from dux_voucher.dux_voucher.doctype.dux_backdating_settings.dux_backdating_settings import (
    default_rule,
)


TARGET = "Student Journal Voucher"


def execute():
    settings = frappe.get_single("Dux Backdating Settings")
    if any(r.target_doctype == TARGET for r in (settings.rules or [])):
        print(f"[dux_voucher] seed_student_journal_voucher_rule: "
              f"already present, no-op")
        return

    settings.append("rules", default_rule(TARGET))
    settings.flags.ignore_permissions = True
    settings.save()
    frappe.db.commit()
    print(f"[dux_voucher] seed_student_journal_voucher_rule: "
          f"added rule for {TARGET}")
