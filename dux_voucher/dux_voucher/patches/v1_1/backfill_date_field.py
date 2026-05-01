"""Backfill ``date_field`` on existing Dux Backdating Rule rows.

When the ``date_field`` column was added to ``Dux Backdating Rule``,
sites that had already run the v1.0 seed patch ended up with rule
rows whose ``date_field`` was blank — including the Purchase Order
rule, which needs ``transaction_date`` to actually fire on PO saves.

This patch fills in the conventional fieldname (per
:data:`DEFAULT_DATE_FIELDS`) on every rule whose ``date_field`` is
still blank, leaving any user-customised value alone. Idempotent.
"""

import frappe

from dux_voucher.dux_voucher.doctype.dux_backdating_settings.dux_backdating_settings import (
    DEFAULT_DATE_FIELDS,
)


def execute():
    settings = frappe.get_single("Dux Backdating Settings")
    changed = 0
    for rule in (settings.rules or []):
        if rule.date_field:
            continue
        wanted = DEFAULT_DATE_FIELDS.get(rule.target_doctype)
        if wanted:
            rule.date_field = wanted
            changed += 1
    if changed:
        settings.flags.ignore_permissions = True
        settings.save()
        frappe.db.commit()
    print(f"[dux_voucher] backfill_date_field: updated {changed} rule(s)")
