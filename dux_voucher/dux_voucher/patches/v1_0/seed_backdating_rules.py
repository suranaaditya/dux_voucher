"""Seed the seven default rule rows on Dux Backdating Settings.

Idempotent — re-running adds only missing rows. After the first
successful migrate this is marked applied in Frappe's patch tracker
and won't run again unless the entry is removed from the tracker.

The same logic also runs from
:meth:`DuxBackdatingSettings.before_save` as a safety net for any
deploy path that skips the patch (fresh ``after_install`` on a brand-
new site, manual record creation, etc.).
"""

import frappe

from dux_voucher.dux_voucher.doctype.dux_backdating_settings.dux_backdating_settings import (
    SUPPORTED_DOCTYPES,
    default_rule,
)


def execute():
    settings = frappe.get_single("Dux Backdating Settings")
    existing = {r.target_doctype for r in (settings.rules or [])
                 if r.target_doctype}
    added = 0
    for dt in SUPPORTED_DOCTYPES:
        if dt not in existing:
            settings.append("rules", default_rule(dt))
            added += 1
    if added:
        settings.flags.ignore_permissions = True
        settings.save()
        frappe.db.commit()
    print(f"[dux_voucher] seed_backdating_rules: added {added} default rule(s)")
