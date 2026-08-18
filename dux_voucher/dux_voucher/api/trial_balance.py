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
from frappe.utils import flt

from dux_voucher.dux_voucher.report.dux_trial_balance.dux_trial_balance import (
    execute as _execute,
    expand_company,
    VIEWS,
)


@frappe.whitelist()
def get_trial_balance(filters=None):
    """Run the engine and return everything the Page needs to draw itself."""
    require_access()
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


TB_ROLE = "Dux Trial Balance"
TB_MANAGER_ROLE = "Dux Trial Balance Manager"


def require_access():
    """Every whitelisted endpoint here checks this.

    Gating the Report and Page records hides the report from the menu; it
    does not stop anyone POSTing to the endpoint directly. The role has to
    be enforced where the data is served, or it is decoration.
    """
    if set(frappe.get_roles()) & {TB_ROLE, TB_MANAGER_ROLE, "System Manager"}:
        return
    frappe.throw(
        _("You do not have access to the Trial Balance. Ask an administrator "
          "for the '{0}' role.").format(TB_ROLE),
        frappe.PermissionError)


def require_manager():
    """Rebuilding is not reading — it re-aggregates every trust company over
    the full GL span and takes minutes."""
    if set(frappe.get_roles()) & {TB_MANAGER_ROLE, "System Manager"}:
        return
    frappe.throw(
        _("Rebuilding the aggregate needs the '{0}' role.").format(TB_MANAGER_ROLE),
        frappe.PermissionError)


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
def get_account_parties(filters=None, accounts=None):
    """The parties behind one control account, for inline expansion.

    Opening a control account in place beats sending someone to a
    different view to answer "who is this ₹1.2 crore of Debtors?". The
    Account -> Party view still exists for scanning every control account
    at once; this is for following a single one.

    ``accounts`` is the list of REAL account names the row represents —
    across a trust the same logical account exists once per company, so
    the page passes back what the row merged rather than guessing.
    """
    require_access()
    from dux_voucher.dux_voucher.report.dux_trial_balance.dux_trial_balance import (
        _slice, _validate, _resolve_party_names, _net_off, _has_value,
        _party_type_mismatch, _default_party_accounts, UNATTRIBUTED)

    if isinstance(filters, str):
        filters = json.loads(filters or "{}")
    if isinstance(accounts, str):
        accounts = json.loads(accounts or "[]")
    accounts = [a for a in (accounts or []) if a]
    if not accounts:
        return []

    f = frappe._dict(filters or {})
    _validate(f)
    _guard(f)
    companies = expand_all(f.get("company"))
    if not companies:
        return []

    values = _slice(companies, ["account", "party_type", "party"], f)
    wanted = set(accounts)

    names = _resolve_party_names(
        {(pt, p) for (a, pt, p) in values.keys() if p and a in wanted})
    default_map = _default_party_accounts(companies)

    # A receivable nets to debit, a payable to credit.
    acct_type = frappe.db.get_value("Account", accounts[0], "account_type")
    natural = "debit" if acct_type == "Receivable" else "credit"

    merged = {}
    for (account, party_type, party), v in values.items():
        if account not in wanted:
            continue
        key = (party_type or "", party or "")
        slot = merged.setdefault(key, {k: 0.0 for k in v})
        for fld in v:
            slot[fld] += flt(v[fld])
        slot["_mismatch"] = slot.get("_mismatch") or _party_type_mismatch(
            account, party_type, default_map)

    out = []
    for (party_type, party), v in merged.items():
        row = {k: val for k, val in v.items() if not k.startswith("_")}
        if f.get("show_net_values"):
            _net_off(row, natural)
        row.update({
            "party_type": party_type or None,
            "party": party or None,
            "label": (UNATTRIBUTED if not party
                      else (names.get((party_type, party)) or party)),
            "is_unattributed": 0 if party else 1,
            "mismatch": 1 if v.get("_mismatch") else 0,
        })
        if _has_value(row) or f.get("show_zero_values"):
            out.append(row)

    out.sort(key=lambda r: (r["is_unattributed"],
                            -abs(flt(r["closing_debit"]) - flt(r["closing_credit"]))))
    return out


def expand_all(selected):
    if isinstance(selected, str):
        selected = [selected] if selected else []
    out, seen = [], set()
    for name in selected or []:
        for co in expand_company(name):
            if co not in seen:
                seen.add(co)
                out.append(co)
    return out


@frappe.whitelist()
def search_companies(txt="", limit=25):
    """Companies and trusts for the Page's picker.

    Group companies are returned first and flagged, because picking a trust
    is the headline gesture — burying it under thirty colleges would hide
    the feature.
    """
    require_access()
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
    require_access()
    return list(VIEWS)


@frappe.whitelist()
def get_fiscal_years():
    """Named explicitly rather than derived from a date — this site has
    overlapping fiscal years (2026-2027 covering Apr-Mar and 2026-2028
    covering Jan-Dec), so 'the' fiscal year for a date is ambiguous."""
    require_access()
    return frappe.get_all(
        "Fiscal Year", filters={"disabled": 0},
        fields=["name", "year_start_date", "year_end_date"],
        order_by="year_start_date desc", limit=12)


@frappe.whitelist()
def aggregate_status():
    require_access()
    from dux_voucher.dux_voucher.api import tb_aggregate
    return tb_aggregate.coverage()
