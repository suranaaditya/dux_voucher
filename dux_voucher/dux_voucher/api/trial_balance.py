"""Whitelisted access to the Trial Balance engine.

The Script Report stays — it is what gives Auto Email Report, Prepared
Report and the existing "Download Formatted TB" button pattern. But the
standard datatable is a dated surface for a report people look at every
day, so the primary UI is a custom Page and this module is what feeds it.

One engine, two surfaces. The Page never reimplements a calculation; it
calls straight through to the same ``execute`` the report uses, so the two
can never disagree.
"""

import json

import frappe
from frappe import _

from dux_voucher.dux_voucher.report.dux_trial_balance.dux_trial_balance import (
    execute as _execute,
    expand_company,
    VIEWS,
)


@frappe.whitelist()
def get_trial_balance(filters=None):
    """Run the engine and return everything the Page needs to draw itself."""
    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    filters = frappe._dict(filters or {})

    _guard(filters)

    columns, rows, message, _chart, summary = _execute(filters)

    return {
        "columns": columns,
        "rows": rows,
        "message": message,
        "summary": summary,
        "source": filters.get("_source") or "live",
        "source_built_at": filters.get("_source_built_at"),
        "companies": filters.get("_resolved_companies") or [],
        "view": filters.get("view"),
    }


def _guard(filters):
    """Company scoping is enforced server-side, not by hiding options in the
    picker. A whitelisted endpoint is reachable directly."""
    from dux_voucher.dux_voucher.api.reports_api import get_permitted_companies

    permitted = set(get_permitted_companies() or [])
    if not permitted:
        return

    selected = filters.get("company") or []
    if isinstance(selected, str):
        selected = [selected]

    resolved = []
    for name in selected:
        resolved.extend(expand_company(name))

    denied = [c for c in resolved if c not in permitted]
    if denied:
        frappe.throw(_("You do not have access to: {0}").format(
            ", ".join(sorted(set(denied))[:5])))


@frappe.whitelist()
def search_companies(txt="", limit=25):
    """Companies and trusts for the Page's picker.

    Group companies are returned first and flagged, because picking a trust
    is the headline gesture — burying it under thirty colleges would hide
    the feature.
    """
    from dux_voucher.dux_voucher.api.reports_api import get_permitted_companies

    permitted = set(get_permitted_companies() or [])
    like = f"%{txt or ''}%"

    rows = frappe.db.sql("""
        SELECT name, abbr, is_group, parent_company
        FROM `tabCompany`
        WHERE name LIKE %(l)s OR abbr LIKE %(l)s
        ORDER BY is_group DESC, lft
        LIMIT %(lim)s
    """, {"l": like, "lim": int(limit)}, as_dict=True)

    out = []
    for r in rows:
        members = expand_company(r.name) if r.is_group else [r.name]
        if permitted and not any(m in permitted for m in members):
            continue
        out.append({
            "value": r.name,
            "abbr": r.abbr,
            "is_group": r.is_group,
            "member_count": len(members),
            "parent": r.parent_company,
        })
    return out


@frappe.whitelist()
def get_view_options():
    return list(VIEWS)


@frappe.whitelist()
def get_fiscal_years():
    """Named explicitly rather than derived from a date — this site has
    overlapping fiscal years (2026-2027 covering Apr-Mar and 2026-2028
    covering Jan-Dec), so 'the' fiscal year for a date is ambiguous."""
    return frappe.get_all(
        "Fiscal Year", filters={"disabled": 0},
        fields=["name", "year_start_date", "year_end_date"],
        order_by="year_start_date desc", limit=12)


@frappe.whitelist()
def aggregate_status():
    from dux_voucher.dux_voucher.api import tb_aggregate
    return tb_aggregate.coverage()
