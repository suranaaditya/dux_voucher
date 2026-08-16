"""Dux Trial Balance — one engine, several groupings.

ERPNext ships two disconnected trial balances: one grouped by account, one
grouped by party, each with its own opening logic and neither able to see
the other. They are not two reports — they are one GL slice asked at two
resolutions. Building them as one engine is what makes reconciliation
possible at all: a separate report can never tell you it disagrees with
its sibling.

Views
    By Account       Chart-of-Accounts tree, child values rolled into groups
    By Party         every party, all party types together
    Account -> Party control accounts expanded into the parties behind them,
                     with an explicit Unattributed row for GL that carries
                     no party (which on this dataset is most of it)
    By Company       one row per company, for multi-company and trust views

Design notes that are load-bearing
    * Cancelled entries are excluded on ``is_cancelled = 0`` alone. This was
      measured, not assumed: across 5,088,888 GL rows on the dev site there
      are zero live rows whose parent JE/PE is cancelled. ERPNext v16 posts
      the reversal on the ORIGINAL posting date and flags both sides, so a
      voucher cancelled today never leaks into today's period.
    * There is no fiscal-year clamp. ERPNext's ``validate_filters`` silently
      rewrites an out-of-year range back into the fiscal year; we accept any
      range and treat fiscal year as a preset that fills the dates.
    * Opening is derived from all history strictly before From Date, plus
      in-period rows flagged ``is_opening = 'Yes'`` — matching ERPNext's
      General Ledger with "Show Opening Entries" off.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate

VIEW_ACCOUNT = "By Account"
VIEW_PARTY = "By Party"
VIEW_ACCOUNT_PARTY = "Account -> Party"
VIEW_COMPANY = "By Company"

VIEWS = (VIEW_ACCOUNT, VIEW_PARTY, VIEW_ACCOUNT_PARTY, VIEW_COMPANY)

VALUE_FIELDS = ("opening_debit", "opening_credit", "debit", "credit",
                "closing_debit", "closing_credit")

# Party types whose display name lives in a differently-named field.
PARTY_NAME_FIELD = {
    "Customer": "customer_name",
    "Supplier": "supplier_name",
    "Employee": "employee_name",
}

# Account types that have a sub-ledger worth reconciling against.
CONTROL_ACCOUNT_TYPES = ("Receivable", "Payable")

# Party type expected on a company's DEFAULT receivable / payable account.
# Deliberately narrow: it is applied only to those two accounts, never to
# account_type generally. A purpose-built account such as "Employee
# Advance" is a Receivable that legitimately carries Employee parties, and
# flagging it would be a false positive that trains people to ignore the
# flag entirely.
DEFAULT_ACCOUNT_EXPECTED = {
    "default_receivable_account": "Customer",
    "default_payable_account": "Supplier",
}

UNATTRIBUTED = "(Unattributed)"


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def execute(filters=None):
    filters = frappe._dict(filters or {})
    _validate(filters)

    companies = resolve_companies(filters)
    filters._resolved_companies = companies
    if not companies:
        return _columns_for(filters, companies), [], _no_company_message(), None, None

    if filters.get("compare"):
        return _build_comparison(filters, companies)

    view = filters.get("view") or VIEW_ACCOUNT
    builder = {
        VIEW_ACCOUNT: _build_by_account,
        VIEW_PARTY: _build_by_party,
        VIEW_ACCOUNT_PARTY: _build_account_party,
        VIEW_COMPANY: _build_by_company,
    }[view]

    data = builder(filters, companies)
    columns = _columns_for(filters, companies)
    message = _build_message(filters, companies, data)
    return columns, data, message, None, _summary(data, filters)


# ══════════════════════════════════════════════════════════════════════
# COMPARISON  (company vs company, period vs period)
# ══════════════════════════════════════════════════════════════════════

def _build_comparison(filters, companies):
    """Run the same engine over several series and lay them side by side.

    Two shapes:
      Company — one column per selected company, over one period. Answers
                "how do the colleges in this trust compare".
      Period  — the same companies over two ranges, with variance. Answers
                "this year against last", or "August against July".

    Showing all six value columns per series would be unreadable at four
    companies, so each series contributes a single signed closing balance
    (debit-positive) and, where exactly two series exist, a variance.
    """
    mode = filters.get("compare")
    view = filters.get("view") or VIEW_ACCOUNT

    if view not in (VIEW_ACCOUNT, VIEW_PARTY):
        frappe.throw(_("Comparison is available on the By Account and "
                       "By Party views."))

    if mode == "Company":
        if len(companies) < 2:
            frappe.throw(_("Select at least two companies to compare."))
        series = [(co, [co], filters.from_date, filters.to_date)
                  for co in companies]
    elif mode == "Period":
        if not filters.get("compare_from") or not filters.get("compare_to"):
            frappe.throw(_("Comparison From and To dates are required for a "
                           "period comparison."))
        series = [
            (_("{0} to {1}").format(filters.from_date, filters.to_date),
             companies, filters.from_date, filters.to_date),
            (_("{0} to {1}").format(filters.compare_from, filters.compare_to),
             companies, getdate(filters.compare_from), getdate(filters.compare_to)),
        ]
    else:
        frappe.throw(_("Unknown comparison mode: {0}").format(mode))

    builder = _build_by_account if view == VIEW_ACCOUNT else _build_by_party
    merged = {}
    order = []
    sources = set()

    for idx, (label, cos, frm, to) in enumerate(series):
        sub = frappe._dict(dict(filters))
        sub.company = cos
        sub.from_date, sub.to_date = frm, to
        sub._pl_reset_date = _pl_reset_date(sub)
        rows = builder(sub, cos)
        sources.add(sub.get("_source") or "live")

        for r in rows:
            if r.get("is_total"):
                continue
            key = _compare_key(r, view)
            slot = merged.get(key)
            if not slot:
                slot = merged[key] = {
                    "label": r.get("account_name") or r.get("party_name"),
                    "account": r.get("account") or key,
                    "parent_account": r.get("parent_account"),
                    "indent": r.get("indent", 0),
                    "is_group_account": r.get("is_group_account", 0),
                    "party_type": r.get("party_type"),
                    "party": r.get("party"),
                    "currency": r.get("currency"),
                }
                order.append(key)
            slot[f"s{idx}"] = flt(r.get("closing_debit")) - flt(r.get("closing_credit"))

    rows = []
    for key in order:
        slot = merged[key]
        for idx in range(len(series)):
            slot.setdefault(f"s{idx}", 0.0)
        if len(series) == 2:
            slot["variance"] = flt(slot["s0"]) - flt(slot["s1"])
        if any(abs(flt(slot.get(f"s{i}"))) >= 0.005 for i in range(len(series))) \
                or filters.get("show_zero_values"):
            rows.append(slot)

    # Each series contributes a SIGNED net (debit-positive), so summing the
    # root nodes yields nil on a ledger that ties. Labelling that "Total"
    # invites the reader to compare 28,894 against rows of 624 million and
    # conclude the report is broken, so the label says what the figure is.
    total = {"label": _("Net of all roots — nil when the ledger ties"),
             "account": "__net__", "is_total": 1, "indent": 0}
    for idx in range(len(series)):
        total[f"s{idx}"] = sum(
            flt(r.get(f"s{idx}")) for r in rows
            if not (filters.get("show_group_accounts") and r.get("parent_account")))
    if len(series) == 2:
        total["variance"] = flt(total["s0"]) - flt(total["s1"])
    rows.append(total)

    columns = _comparison_columns(series, view)
    src = "aggregate" if sources == {"aggregate"} else (
        "mixed" if len(sources) > 1 else "live")
    message = _("<b>{0}</b> series &nbsp;·&nbsp; {1} &nbsp;·&nbsp; {2}").format(
        len(series), _("comparing by {0}").format(mode.lower()),
        _("monthly aggregate") if src == "aggregate" else
        (_("mixed sources") if src == "mixed" else _("live GL")))
    return columns, rows, message, None, None


def _compare_key(row, view):
    if view == VIEW_PARTY:
        return f"{row.get('party_type')}::{row.get('party')}"
    return row.get("account")


def _comparison_columns(series, view):
    label = _("Party") if view == VIEW_PARTY else _("Account")
    cols = [{"fieldname": "label", "label": label, "fieldtype": "Data",
             "width": 300}]
    for idx, (name, _cos, _f, _t) in enumerate(series):
        cols.append({"fieldname": f"s{idx}", "label": name,
                     "fieldtype": "Currency", "options": "currency",
                     "width": 150})
    if len(series) == 2:
        cols.append({"fieldname": "variance", "label": _("Variance"),
                     "fieldtype": "Currency", "options": "currency",
                     "width": 150})
    cols.append({"fieldname": "currency", "label": _("Currency"),
                 "fieldtype": "Link", "options": "Currency", "hidden": 1})
    return cols


def _validate(filters):
    if not filters.get("from_date") or not filters.get("to_date"):
        frappe.throw(_("From Date and To Date are both required."))
    filters.from_date = getdate(filters.from_date)
    filters.to_date = getdate(filters.to_date)
    if filters.from_date > filters.to_date:
        frappe.throw(_("From Date cannot be after To Date."))

    view = filters.get("view") or VIEW_ACCOUNT
    if view not in VIEWS:
        frappe.throw(_("Unknown view: {0}").format(view))

    filters._pl_reset_date = _pl_reset_date(filters)


def _pl_reset_date(filters):
    """The date from which Income and Expense opening should be counted.

    Profit-and-loss accounts are closed annually, so their opening at the
    start of a fiscal year is zero — carrying five years of expenses into
    an opening column would be meaningless and would dwarf every real
    figure. Balance-sheet accounts carry forward indefinitely and are
    unaffected.

    Normally a Period Closing Voucher would have moved last year's P&L into
    retained earnings, and ERPNext would read the closing balance. This site
    has no Period Closing Vouchers at all, so the reset has to be applied at
    query time or P&L openings run to hundreds of crores.

    Returns None when the user asks to see unclosed prior-year P&L, or when
    no fiscal year covers From Date.
    """
    if filters.get("show_unclosed_fy_pl_balances"):
        return None

    # An explicitly chosen fiscal year wins — this site has overlapping
    # fiscal years, so deriving one from a date is ambiguous.
    if filters.get("fiscal_year"):
        start = frappe.db.get_value("Fiscal Year", filters.get("fiscal_year"),
                                    "year_start_date")
        if start:
            return getdate(start)

    row = frappe.db.sql("""
        SELECT year_start_date FROM `tabFiscal Year`
        WHERE disabled = 0
          AND year_start_date <= %(d)s AND year_end_date >= %(d)s
        ORDER BY year_start_date DESC LIMIT 1
    """, {"d": filters.from_date}, as_dict=True)
    return getdate(row[0].year_start_date) if row else None


def _no_company_message():
    return _("<b>No company selected.</b> Pick one or more companies, or a "
             "group company to include everything beneath it.")


# ══════════════════════════════════════════════════════════════════════
# COMPANY RESOLUTION  (trust / group expansion)
# ══════════════════════════════════════════════════════════════════════

def resolve_companies(filters):
    """Expand the company filter into a concrete list of ledger companies.

    A group company stands for its whole subtree, so selecting a trust
    selects everything under it. This reads ERPNext's native Company
    nested set (lft/rgt) rather than maintaining a parallel hierarchy —
    production already maintains that tree, and two sources of truth for
    parentage is the one outcome worse than either.
    """
    selected = filters.get("company")
    if isinstance(selected, str):
        selected = [selected] if selected else []
    selected = [c for c in (selected or []) if c]

    if not selected:
        return []

    out = []
    seen = set()
    for name in selected:
        for co in expand_company(name):
            if co not in seen:
                seen.add(co)
                out.append(co)
    return out


def expand_company(name):
    """A group company -> every non-group company beneath it (itself
    excluded, since a group company holds no GL of its own). A leaf
    company -> just itself."""
    row = frappe.db.get_value("Company", name, ["is_group", "lft", "rgt"],
                              as_dict=True)
    if not row:
        return []
    if not row.is_group:
        return [name]

    return frappe.db.get_all(
        "Company",
        filters={"lft": [">=", row.lft], "rgt": ["<=", row.rgt], "is_group": 0},
        pluck="name", order_by="lft") or []


@frappe.whitelist()
def get_company_options(doctype, txt, searchfield, start, page_len, filters):
    """Link-field query that offers group companies too, labelled, so a
    user can pick a trust and get its members."""
    txt = "%" + (txt or "") + "%"
    rows = frappe.db.sql("""
        SELECT name, is_group FROM `tabCompany`
        WHERE name LIKE %(txt)s ORDER BY is_group DESC, lft LIMIT %(pl)s OFFSET %(st)s
    """, {"txt": txt, "pl": page_len or 20, "st": start or 0})
    return [(r[0], _("group") if r[1] else "") for r in rows]


# ══════════════════════════════════════════════════════════════════════
# THE GL SLICE  — one query shape, parameterised by grouping
# ══════════════════════════════════════════════════════════════════════

def _gl_aggregate(companies, group_cols, filters, opening):
    """Aggregate GL Entry over ``companies`` grouped by ``group_cols``.

    opening=True  -> everything strictly before From Date, plus in-period
                     rows flagged is_opening='Yes'
    opening=False -> the period itself, is_opening='No'

    Returns a list of dicts carrying the group columns plus debit/credit.
    """
    if not companies:
        return []

    params = {
        "companies": tuple(companies),
        "from_date": filters.from_date,
        "to_date": filters.to_date,
    }

    where = ["gle.company IN %(companies)s", "gle.is_cancelled = 0"]
    joins = ""

    if opening:
        where.append(
            "( gle.posting_date < %(from_date)s"
            "  OR (gle.is_opening = 'Yes'"
            "      AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s) )")
        # Reset Income/Expense opening at the fiscal-year boundary; see
        # _pl_reset_date. Balance-sheet accounts are untouched.
        if filters.get("_pl_reset_date"):
            params["pl_reset"] = filters["_pl_reset_date"]
            joins = "JOIN `tabAccount` acc ON acc.name = gle.account"
            where.append("( acc.root_type NOT IN ('Income', 'Expense')"
                         "  OR gle.posting_date >= %(pl_reset)s )")
    else:
        where.append("gle.posting_date BETWEEN %(from_date)s AND %(to_date)s")
        where.append("gle.is_opening = 'No'")

    if filters.get("cost_center"):
        cc = filters.get("cost_center")
        params["cost_center"] = tuple(cc if isinstance(cc, (list, tuple)) else [cc])
        where.append("gle.cost_center IN %(cost_center)s")

    if filters.get("project"):
        pr = filters.get("project")
        params["project"] = tuple(pr if isinstance(pr, (list, tuple)) else [pr])
        where.append("gle.project IN %(project)s")

    if filters.get("party_type_filter"):
        params["ptf"] = filters.get("party_type_filter")
        where.append("gle.party_type = %(ptf)s")

    select = ", ".join(f"gle.{c} AS {c}" for c in group_cols)
    group = ", ".join(f"gle.{c}" for c in group_cols)

    return frappe.db.sql(f"""
        SELECT {select},
               COALESCE(SUM(gle.debit), 0)  AS debit,
               COALESCE(SUM(gle.credit), 0) AS credit
        FROM `tabGL Entry` gle
        {joins}
        WHERE {' AND '.join(where)}
        GROUP BY {group}
    """, params, as_dict=True)


def _slice(companies, group_cols, filters):
    """Opening + period keyed by the grouping tuple, from whichever tier
    can answer the request.

    Tier is chosen by scope and stated on the report. A single company
    queries live in about a second and is always current; a wide
    multi-company request reads the monthly aggregate because live would
    take 38 seconds. The report never switches silently — two sources with
    different freshness, swapped without saying so, is how a reconciliation
    tool loses the trust that makes it useful.
    """
    from dux_voucher.dux_voucher.api import tb_aggregate

    live_threshold = int(filters.get("live_company_threshold") or 3)
    wants_fast = len(companies) > live_threshold

    if wants_fast and not filters.get("force_live"):
        if tb_aggregate.can_serve(companies, filters.from_date, filters.to_date):
            filters._source = "aggregate"
            filters._source_built_at = tb_aggregate.built_at()
            return tb_aggregate.fetch(companies, group_cols,
                                      filters.from_date, filters.to_date,
                                      filters.get("_pl_reset_date"))
        filters._source_note = _(
            "the monthly aggregate cannot answer this request — either it "
            "does not cover every selected company, or the dates are not "
            "whole months")

    filters._source = "live"
    return _slice_live(companies, group_cols, filters)


def _slice_live(companies, group_cols, filters):
    key = lambda r: tuple(r.get(c) for c in group_cols)  # noqa: E731

    out = {}
    for r in _gl_aggregate(companies, group_cols, filters, opening=True):
        k = key(r)
        e = out.setdefault(k, _blank_row())
        e["opening_debit"] += flt(r.debit)
        e["opening_credit"] += flt(r.credit)
    for r in _gl_aggregate(companies, group_cols, filters, opening=False):
        k = key(r)
        e = out.setdefault(k, _blank_row())
        e["debit"] += flt(r.debit)
        e["credit"] += flt(r.credit)

    for e in out.values():
        e["closing_debit"] = e["opening_debit"] + e["debit"]
        e["closing_credit"] = e["opening_credit"] + e["credit"]
    return out


def _blank_row():
    return {f: 0.0 for f in VALUE_FIELDS}


# ══════════════════════════════════════════════════════════════════════
# PRESENTATION HELPERS
# ══════════════════════════════════════════════════════════════════════

def _net_off(row, natural="debit"):
    """Collapse opening and closing onto one side.

    ``natural`` is the side this row's balance normally sits on, so an
    asset nets into Debit and a liability into Credit. Where the balance
    runs contrary to its nature the figure moves to the other column
    rather than going negative.
    """
    other = "credit" if natural == "debit" else "debit"
    for stage in ("opening", "closing"):
        a, b = f"{stage}_{natural}", f"{stage}_{other}"
        row[a] = flt(row[a]) - flt(row[b])
        if row[a] < 0:
            row[b] = abs(row[a])
            row[a] = 0.0
        else:
            row[b] = 0.0


def _natural_side(root_type):
    return "debit" if root_type in ("Asset", "Expense") else "credit"


def _has_value(row, tol=0.005):
    return any(abs(flt(row.get(f))) >= tol for f in VALUE_FIELDS)


def _total_row(rows, label, only_top_level=False):
    total = _blank_row()
    total.update({"account": f"'{label}'", "account_name": f"'{label}'",
                  "party": f"'{label}'", "company": f"'{label}'",
                  "is_total": 1, "indent": 0, "has_value": True})
    for r in rows:
        if r.get("is_total"):
            continue
        if only_top_level and r.get("parent_account"):
            continue
        for f in VALUE_FIELDS:
            total[f] += flt(r.get(f))
    return total


def _default_party_accounts(companies):
    """{account name -> expected party type} for each company's default
    receivable and payable accounts."""
    out = {}
    for co in companies:
        for field, expected in DEFAULT_ACCOUNT_EXPECTED.items():
            acc = frappe.get_cached_value("Company", co, field)
            if acc:
                out[acc] = expected
    return out


def _party_type_mismatch(account, party_type, default_map):
    """True when a party sits on the company's default customer or supplier
    control account while being the wrong type for it.

    Reported, never corrected — a reporting change does not rewrite the
    ledger. On the dev data this catches an Employee carrying Dr 10,000 on
    Debtors, which ERPNext's party report cannot show because it runs one
    party type per execution and nobody thinks to run it for Employee.

    Scoped to the two default accounts on purpose. An "Employee Advance"
    account is also a Receivable and legitimately carries Employee parties;
    flagging that would be noise.
    """
    if not account or not party_type:
        return False
    expected = default_map.get(account)
    if not expected:
        return False
    return party_type != expected


# ══════════════════════════════════════════════════════════════════════
# VIEW — BY ACCOUNT
# ══════════════════════════════════════════════════════════════════════

def _account_master(companies):
    """Accounts across the selected companies.

    For a single company the account name is the natural key. Across
    several, the same logical account carries a different suffix per
    company (``Cash - JEWIPL`` / ``Cash - DD``), so rows are merged on
    account_number + account_name the way a consolidation would.
    """
    accounts = frappe.db.sql("""
        SELECT name, company, account_name, account_number, parent_account,
               root_type, report_type, account_type, is_group, lft, rgt
        FROM `tabAccount`
        WHERE company IN %(companies)s
        ORDER BY lft
    """, {"companies": tuple(companies)}, as_dict=True)
    return accounts


def _merge_key(acc, multi):
    """Key that folds the same logical account across companies.

    Single company: the account name is already unique, use it as-is.

    Multi-company: the RGI chart of accounts was cloned per company and
    then drifted, so the same root appears as "Application of Funds
    (Assets)" in one company and "Application Of Funds(Assets)" in
    another. Matching on the exact string produced two of every root in a
    ten-company trust, which is technically true and completely unusable.

    Case and whitespace are therefore normalised away. Punctuation is NOT
    — "Advance to Staff" and "Advance to Staff (Old)" must stay distinct.
    Account number, where present, takes precedence because it is the
    stable identity.
    """
    if not multi:
        return acc.name

    num = (acc.account_number or "").strip()
    if num:
        return f"#{num}"
    return "".join((acc.account_name or "").lower().split())


def _build_by_account(filters, companies):
    multi = len(companies) > 1
    accounts = _account_master(companies)
    if not accounts:
        return []

    values = _slice(companies, ["account"], filters)

    # Fold per-company accounts onto their merge key.
    by_name = {a.name: a for a in accounts}
    nodes = {}
    for acc in accounts:
        k = _merge_key(acc, multi)
        node = nodes.get(k)
        if not node:
            node = nodes[k] = {
                "key": k,
                "account_name": (f"{acc.account_number} - {acc.account_name}"
                                 if acc.account_number else acc.account_name),
                "parent_key": None,
                "root_type": acc.root_type,
                "account_type": acc.account_type,
                "is_group": acc.is_group,
                "lft": acc.lft,
                "members": [],
                **_blank_row(),
            }
        node["members"].append(acc.name)
        if acc.parent_account:
            parent = by_name.get(acc.parent_account)
            if parent:
                node["parent_key"] = _merge_key(parent, multi)

        v = values.get((acc.name,))
        if v:
            for f in VALUE_FIELDS:
                node[f] += flt(v[f])

    # Roll leaf values up into ancestors, deepest first so a value lands in
    # every ancestor exactly once.
    #
    # Ordering by DEPTH, not by lft. lft is a per-company pre-order index,
    # so across merged companies the ranges overlap and a parent in one
    # company can sort after a child in another — which rolls values into
    # a parent that has already been summed, or misses it entirely. Depth
    # is the property that actually matters and is company-independent.
    depth = _depth_map(nodes)
    for node in sorted(nodes.values(), key=lambda n: depth[n["key"]], reverse=True):
        pk = node["parent_key"]
        if pk and pk in nodes and pk != node["key"]:
            for f in VALUE_FIELDS:
                nodes[pk][f] += flt(node[f])

    show_net = filters.get("show_net_values")
    rows = []
    for node in _tree_order(nodes, depth):
        if show_net:
            _net_off(node, _natural_side(node["root_type"]))
        row = {
            "account": node["key"],
            "account_name": node["account_name"],
            "parent_account": node["parent_key"],
            "indent": 0,
            "is_group_account": node["is_group"],
            "root_type": node["root_type"],
            "account_type": node["account_type"],
            "currency": _company_currency(companies[0]),
        }
        for f in VALUE_FIELDS:
            row[f] = flt(node[f])
        row["has_value"] = _has_value(row)
        rows.append(row)

    rows = _apply_indent(rows)

    if not filters.get("show_group_accounts"):
        rows = [r for r in rows if not r.get("is_group_account")]
        for r in rows:
            r["indent"] = 0
            r["parent_account"] = None

    if not filters.get("show_zero_values"):
        rows = _drop_zero_keeping_ancestors(rows)

    carry = _unclosed_pl_row(companies, filters, _company_currency(companies[0]))
    if carry:
        rows.append(carry)

    rows.append(_total_row(rows, _("Total"),
                           only_top_level=bool(filters.get("show_group_accounts"))))
    return rows


def _unclosed_pl_row(companies, filters, currency):
    """The balancing line for prior-year profit or loss that was never closed.

    Resetting P&L opening at the fiscal-year boundary removes prior-year
    income and expense from the opening columns. In a normal ledger a Period
    Closing Voucher would already have moved that net into reserves, so the
    trial balance still ties. This site has no Period Closing Vouchers at
    all, so the amount simply vanishes and the report lands hundreds of
    crores out of balance — which is exactly what ERPNext's own Trial
    Balance shows here, with no explanation offered.

    Rather than print a broken total, we surface the missing figure as a
    clearly-labelled computed row. Accumulated loss carries as a debit,
    accumulated profit as a credit, mirroring what closing would have
    posted to retained earnings.

    Returns None when the reset is off or there is nothing to carry.
    """
    reset = filters.get("_pl_reset_date")
    if not reset:
        return None

    # Take it from whichever tier served the rest of the report. Querying
    # live here while the balances came from the aggregate was measurably
    # worse than not having an aggregate at all — the fast path returned in
    # milliseconds and then this held the request open for ~40s.
    if filters.get("_source") == "aggregate":
        from dux_voucher.dux_voucher.api import tb_aggregate
        net = flt(tb_aggregate.unclosed_pl(
            companies, filters.from_date, filters.to_date, reset))
        return _carry_row(net, currency)

    row = frappe.db.sql("""
        SELECT COALESCE(SUM(gle.debit), 0)  AS debit,
               COALESCE(SUM(gle.credit), 0) AS credit
        FROM `tabGL Entry` gle
        JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company IN %(companies)s
          AND gle.is_cancelled = 0
          AND acc.root_type IN ('Income', 'Expense')
          AND ( gle.posting_date < %(from_date)s
                OR (gle.is_opening = 'Yes'
                    AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s) )
          AND gle.posting_date < %(pl_reset)s
    """, {"companies": tuple(companies), "from_date": filters.from_date,
          "to_date": filters.to_date, "pl_reset": reset}, as_dict=True)

    if not row:
        return None
    return _carry_row(flt(row[0].debit) - flt(row[0].credit), currency)


def _carry_row(net, currency):
    if abs(net) < 0.005:
        return None

    label = (_("Accumulated Loss b/f — P&L never closed")
             if net > 0 else _("Accumulated Profit b/f — P&L never closed"))

    out = _blank_row()
    out.update({
        "account": "__unclosed_pl__",
        "account_name": label,
        "parent_account": None,
        "indent": 0,
        "is_group_account": 0,
        "is_computed": 1,
        "currency": currency,
        "has_value": True,
        "opening_debit": net if net > 0 else 0.0,
        "opening_credit": -net if net < 0 else 0.0,
        "closing_debit": net if net > 0 else 0.0,
        "closing_credit": -net if net < 0 else 0.0,
    })
    return out


def _depth_map(nodes):
    """Depth of every node from its parent chain, cycle-guarded."""
    cache = {}

    def depth(key, guard=0):
        if key in cache:
            return cache[key]
        node = nodes.get(key)
        pk = node.get("parent_key") if node else None
        if not node or not pk or pk not in nodes or pk == key or guard > 30:
            cache[key] = 0
            return 0
        d = depth(pk, guard + 1) + 1
        cache[key] = d
        return d

    for k in nodes:
        depth(k)
    return cache


def _tree_order(nodes, depth):
    """Parent-before-child ordering that survives a multi-company merge.

    Sorting by lft alone interleaves companies, because each company's
    nested set numbers from its own root. This walks the merged parent
    map depth-first, ordering siblings by their lowest member lft so the
    natural chart-of-accounts sequence is preserved inside each level.
    """
    children = {}
    roots = []
    for key, node in nodes.items():
        pk = node.get("parent_key")
        if pk and pk in nodes and pk != key:
            children.setdefault(pk, []).append(key)
        else:
            roots.append(key)

    for lst in children.values():
        lst.sort(key=lambda k: (nodes[k]["lft"], nodes[k]["account_name"]))
    roots.sort(key=lambda k: (nodes[k]["lft"], nodes[k]["account_name"]))

    out = []
    seen = set()

    def walk(key, guard=0):
        if key in seen or guard > 30:
            return
        seen.add(key)
        out.append(nodes[key])
        for c in children.get(key, []):
            walk(c, guard + 1)

    for r in roots:
        walk(r)
    # Anything unreachable (a broken parent link) still gets emitted, so a
    # data problem never silently swallows a balance.
    for key, node in nodes.items():
        if key not in seen:
            out.append(node)
    return out


def _apply_indent(rows):
    by_key = {r["account"]: r for r in rows}
    depth_cache = {}

    def depth(key, guard=0):
        if key in depth_cache:
            return depth_cache[key]
        r = by_key.get(key)
        if not r or not r.get("parent_account") or guard > 20:
            depth_cache[key] = 0
            return 0
        d = depth(r["parent_account"], guard + 1) + 1
        depth_cache[key] = d
        return d

    for r in rows:
        r["indent"] = depth(r["account"])
    return rows


def _drop_zero_keeping_ancestors(rows):
    """Hide empty rows, but keep any group that still has a visible
    descendant — otherwise the tree loses its spine and children become
    unreachable."""
    keep = {r["account"] for r in rows if r.get("has_value")}
    by_key = {r["account"]: r for r in rows}
    for k in list(keep):
        cur = by_key.get(k)
        guard = 0
        while cur and cur.get("parent_account") and guard < 20:
            keep.add(cur["parent_account"])
            cur = by_key.get(cur["parent_account"])
            guard += 1
    return [r for r in rows if r["account"] in keep]


def _company_currency(company):
    return frappe.get_cached_value("Company", company, "default_currency") or "INR"


# ══════════════════════════════════════════════════════════════════════
# VIEW — BY PARTY   (all party types at once)
# ══════════════════════════════════════════════════════════════════════

def _build_by_party(filters, companies):
    values = _slice(companies, ["party_type", "party"], filters)
    show_net = filters.get("show_net_values")
    currency = _company_currency(companies[0])

    names = _resolve_party_names(
        {(pt, p) for (pt, p) in values.keys() if p})

    rows = []
    for (party_type, party), v in values.items():
        if not party:
            continue
        row = dict(v)
        if show_net:
            _net_off(row, "debit" if party_type == "Customer" else "credit")
        row.update({
            "party_type": party_type,
            "party": party,
            "party_name": names.get((party_type, party)) or party,
            "currency": currency,
            "indent": 0,
        })
        row["has_value"] = _has_value(row)
        if row["has_value"] or filters.get("show_zero_values"):
            rows.append(row)

    rows.sort(key=lambda r: (r["party_type"] or "", r["party_name"] or ""))
    rows.append(_total_row(rows, _("Total")))
    return rows


def _resolve_party_names(pairs):
    by_type = {}
    for pt, p in pairs:
        if pt in PARTY_NAME_FIELD:
            by_type.setdefault(pt, set()).add(p)
    names = {}
    for pt, ps in by_type.items():
        field = PARTY_NAME_FIELD[pt]
        for n, dn in frappe.db.sql(
                f"SELECT name, `{field}` FROM `tab{pt}` WHERE name IN %(p)s",
                {"p": tuple(ps)}):
            if dn:
                names[(pt, n)] = dn
    return names


# ══════════════════════════════════════════════════════════════════════
# VIEW — ACCOUNT -> PARTY   (the reconciliation view)
# ══════════════════════════════════════════════════════════════════════

def _build_account_party(filters, companies):
    """Control accounts expanded into the parties behind them.

    Every account row is followed by its parties, and — where the account
    carries GL with no party at all — an explicit Unattributed row. That
    row is not an error state: on this dataset most Receivable/Payable
    movement has no party, so hiding it would misrepresent the ledger.
    """
    values = _slice(companies, ["account", "party_type", "party"], filters)
    if not values:
        return []

    acc_meta = {a.name: a for a in _account_master(companies)}
    currency = _company_currency(companies[0])
    show_net = filters.get("show_net_values")
    default_map = _default_party_accounts(companies)

    names = _resolve_party_names(
        {(pt, p) for (_a, pt, p) in values.keys() if p})

    # Group by account, then by party within it.
    per_account = {}
    for (account, party_type, party), v in values.items():
        per_account.setdefault(account, []).append((party_type, party, v))

    rows = []
    for account in sorted(per_account.keys()):
        meta = acc_meta.get(account)
        # Only control accounts are interesting here; a plain expense
        # account has no sub-ledger to reconcile against.
        if filters.get("control_accounts_only") and meta and \
                meta.account_type not in CONTROL_ACCOUNT_TYPES:
            continue

        children = per_account[account]
        parent = _blank_row()
        for _pt, _p, v in children:
            for f in VALUE_FIELDS:
                parent[f] += flt(v[f])

        natural = _natural_side(meta.root_type if meta else "Asset")
        parent_row = dict(parent)
        if show_net:
            _net_off(parent_row, natural)
        parent_row.update({
            "account": account,
            "account_name": account,
            "parent_account": None,
            "indent": 0,
            "is_group_account": 0,
            "account_type": meta.account_type if meta else None,
            "currency": currency,
        })
        parent_row["has_value"] = _has_value(parent_row)
        if not parent_row["has_value"] and not filters.get("show_zero_values"):
            continue
        rows.append(parent_row)

        for party_type, party, v in sorted(
                children, key=lambda c: (c[0] or "", c[1] or "")):
            child = dict(v)
            if show_net:
                _net_off(child, natural)
            unattributed = not party
            child.update({
                "account": f"{account}::{party_type or ''}::{party or UNATTRIBUTED}",
                "account_name": (UNATTRIBUTED if unattributed
                                 else (names.get((party_type, party)) or party)),
                "parent_account": account,
                "indent": 1,
                "is_group_account": 0,
                "party_type": party_type,
                "party": party,
                "currency": currency,
                "is_unattributed": 1 if unattributed else 0,
                "mismatch": 1 if _party_type_mismatch(
                    account, party_type, default_map) else 0,
            })
            child["has_value"] = _has_value(child)
            if child["has_value"] or filters.get("show_zero_values"):
                rows.append(child)

    rows.append(_total_row(rows, _("Total"), only_top_level=True))
    return rows


# ══════════════════════════════════════════════════════════════════════
# VIEW — BY COMPANY
# ══════════════════════════════════════════════════════════════════════

def _build_by_company(filters, companies):
    values = _slice(companies, ["company"], filters)
    show_net = filters.get("show_net_values")
    rows = []
    for (company,), v in values.items():
        row = dict(v)
        if show_net:
            # A whole company nets to whichever side it lands on; treat
            # debit as natural so the sign convention stays predictable.
            _net_off(row, "debit")
        row.update({
            "company": company,
            "account_name": company,
            "currency": _company_currency(company),
            "indent": 0,
        })
        row["has_value"] = _has_value(row)
        if row["has_value"] or filters.get("show_zero_values"):
            rows.append(row)
    rows.sort(key=lambda r: r["company"])
    rows.append(_total_row(rows, _("Total")))
    return rows


# ══════════════════════════════════════════════════════════════════════
# COLUMNS
# ══════════════════════════════════════════════════════════════════════

def _money(fieldname, label, width=130):
    return {"fieldname": fieldname, "label": label, "fieldtype": "Currency",
            "options": "currency", "width": width}


def _columns_for(filters, companies):
    view = filters.get("view") or VIEW_ACCOUNT

    if view == VIEW_PARTY:
        lead = [
            {"fieldname": "party_type", "label": _("Party Type"),
             "fieldtype": "Data", "width": 110},
            {"fieldname": "party", "label": _("Party"),
             "fieldtype": "Data", "width": 150},
            {"fieldname": "party_name", "label": _("Name"),
             "fieldtype": "Data", "width": 240},
        ]
    elif view == VIEW_COMPANY:
        lead = [{"fieldname": "company", "label": _("Company"),
                 "fieldtype": "Data", "width": 340}]
    else:
        lead = [{"fieldname": "account_name", "label": _("Account"),
                 "fieldtype": "Data", "width": 340}]

    return lead + [
        _money("opening_debit", _("Opening (Dr)")),
        _money("opening_credit", _("Opening (Cr)")),
        _money("debit", _("Debit")),
        _money("credit", _("Credit")),
        _money("closing_debit", _("Closing (Dr)")),
        _money("closing_credit", _("Closing (Cr)")),
        {"fieldname": "currency", "label": _("Currency"), "fieldtype": "Link",
         "options": "Currency", "hidden": 1},
    ]


# ══════════════════════════════════════════════════════════════════════
# MESSAGE + SUMMARY
# ══════════════════════════════════════════════════════════════════════

def _build_message(filters, companies, data):
    """A short provenance line above the report — which companies, which
    source, and whether it ties. A reconciliation tool that does not say
    where its numbers came from does not get trusted."""
    total = next((r for r in data if r.get("is_total")), None)
    bits = [_("<b>{0}</b> compan{1}").format(
        len(companies), "y" if len(companies) == 1 else "ies")]

    if filters.get("_source") == "aggregate":
        stamp = filters.get("_source_built_at")
        bits.append(_("monthly aggregate{0}").format(
            _(" · built {0}").format(str(stamp)[:16]) if stamp else ""))
    else:
        bits.append(_("live GL"))
    if filters.get("_source_note"):
        bits.append(_("<span style='color:#A65A00'>{0}</span>").format(
            filters.get("_source_note")))

    if total:
        diff = flt(total["closing_debit"]) - flt(total["closing_credit"])
        if abs(diff) < 0.005:
            bits.append(_("<span style='color:#146B4A'>&#10003; tied</span>"))
        else:
            bits.append(_("<span style='color:#B3261E'>&#9888; out of balance "
                          "by {0}</span>").format(frappe.format_value(
                              diff, {"fieldtype": "Currency"})))

    carry = next((r for r in data if r.get("is_computed")), None)
    if carry:
        bits.append(_("<span style='color:#A65A00'>includes a computed "
                      "carry-forward — no Period Closing Voucher has been "
                      "run for this company</span>"))

    mism = [r for r in data if r.get("mismatch")]
    if mism:
        bits.append(_("<span style='color:#A65A00'>{0} party-type "
                      "mismatch(es)</span>").format(len(mism)))

    unatt = [r for r in data if r.get("is_unattributed")]
    if unatt:
        bits.append(_("{0} unattributed row(s)").format(len(unatt)))

    return "  &nbsp;·&nbsp;  ".join(bits)


def _summary(data, filters):
    total = next((r for r in data if r.get("is_total")), None)
    if not total:
        return None
    diff = flt(total["closing_debit"]) - flt(total["closing_credit"])
    tied = abs(diff) < 0.005
    return [
        {"label": _("Closing (Dr)"), "value": flt(total["closing_debit"]),
         "datatype": "Currency", "indicator": "blue"},
        {"label": _("Closing (Cr)"), "value": flt(total["closing_credit"]),
         "datatype": "Currency", "indicator": "blue"},
        {"label": _("Difference"), "value": diff, "datatype": "Currency",
         "indicator": "green" if tied else "red"},
    ]
