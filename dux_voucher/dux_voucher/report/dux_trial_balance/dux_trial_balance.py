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
from frappe.utils import flt, formatdate, getdate

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
    "Student": "student_name",
}

# Account types that have a sub-ledger worth reconciling against.
CONTROL_ACCOUNT_TYPES = ("Receivable", "Payable")

# The student ledger keeps a blank account_type (so ERPNext never demands a
# party on it) but carries one Student per line — it opens into its students
# like any other control account. Matched by account name, which is how the
# app resolves it per company (api/student_fee.py).
STUDENT_CONTROL_ACCOUNT_NAME = "Admission/Registration Fee (Provisional)"


def _is_control(account_type, account_name):
    return (account_type in CONTROL_ACCOUNT_TYPES
            or account_name == STUDENT_CONTROL_ACCOUNT_NAME)

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
    # Mutate the caller's dict rather than a copy.
    #
    # execute() stamps provenance onto filters as it runs — which tier
    # served the request, when the aggregate was built, which companies a
    # trust expanded to. Wrapping unconditionally in a fresh _dict threw
    # all of that away at the boundary, so the page's own status pill read
    # "Live GL · 0 companies" while the query had in fact used the
    # aggregate across 34 companies. The report was telling the truth
    # internally and lying on screen, which is the one failure mode a
    # reconciliation tool cannot afford.
    if not isinstance(filters, frappe._dict):
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
        # Labelled in the site's date format, like every other date on screen.
        series = [
            (_("{0} to {1}").format(formatdate(filters.from_date), formatdate(filters.to_date)),
             companies, filters.from_date, filters.to_date),
            (_("{0} to {1}").format(formatdate(filters.compare_from), formatdate(filters.compare_to)),
             companies, getdate(filters.compare_from), getdate(filters.compare_to)),
        ]
    else:
        frappe.throw(_("Unknown comparison mode: {0}").format(mode))

    builder = _build_by_account if view == VIEW_ACCOUNT else _build_by_party
    if mode == "Company":
        return _compare_companies(filters, companies, series, view, builder)

    merged = {}
    order = []
    sources, built = set(), set()

    for idx, (label, cos, frm, to) in enumerate(series):
        sub = frappe._dict(dict(filters))
        sub.company = cos
        sub.from_date, sub.to_date = frm, to
        # The chosen Fiscal Year belongs to the main range. A comparison range
        # resets income and expense at the start of its OWN year, or "this
        # year against last" set year-to-date against part of a year.
        if (frm, to) != (filters.from_date, filters.to_date):
            sub.fiscal_year = None
        sub._pl_reset_date = _pl_reset_date(sub)
        rows = builder(sub, cos)
        sources.add(sub.get("_source") or "live")
        if sub.get("_source_built_at"):
            built.add(str(sub._source_built_at))

        for r in rows:
            if r.get("is_total"):
                continue
            key = _compare_key(r, view)
            slot = merged.get(key)
            if not slot:
                slot = merged[key] = _compare_slot(r, key)
                order.append(key)
            slot[f"s{idx}"] = flt(r.get("closing_debit")) - flt(r.get("closing_credit"))

    return _comparison_result(filters, series, view, mode, merged, order, sources, built)


def _compare_companies(filters, companies, series, view, builder):
    """Compare = Company: ONE run over every company with company columns,
    each company's signed closing becoming its series.

    Run company by company, each series was a one-company trial balance keyed
    by that company's own account names ("Cash - A", "Cash - B"), so no two
    companies ever met on a row: company A's tree printed with B's column
    blank, then B's tree below it. One run merges the same account across
    companies exactly as the consolidated view does, and a trust reads the
    monthly aggregate instead of querying each college live."""
    sub = frappe._dict(dict(filters))
    sub.compare = None
    sub.view = view
    sub.company_columns = 1
    rows = builder(sub, companies)

    merged, order = {}, []
    for r in rows:
        if r.get("is_total"):
            continue
        key = _compare_key(r, view)
        slot = merged[key] = _compare_slot(r, key)
        order.append(key)
        for idx, c in enumerate(r.get("cv") or []):
            # Closing Dr less Closing Cr: the same signed figure whether or
            # not the company's own balance was netted onto one side.
            slot[f"s{idx}"] = (flt(c[4]) - flt(c[5])) if c else 0.0

    return _comparison_result(filters, series, view, "Company", merged, order,
                              {sub.get("_source") or "live"},
                              {str(sub._source_built_at)} if sub.get("_source_built_at") else set())


def _compare_slot(row, key):
    return {
        "label": row.get("account_name") or row.get("party_name"),
        "account": row.get("account") or key,
        "parent_account": row.get("parent_account"),
        "indent": row.get("indent", 0),
        "is_group_account": row.get("is_group_account", 0),
        "party_type": row.get("party_type"),
        "party": row.get("party"),
        "currency": row.get("currency"),
    }


def _comparison_result(filters, series, view, mode, merged, order, sources, built=()):
    rows = []
    for key in order:
        slot = merged[key]
        for idx in range(len(series)):
            slot.setdefault(f"s{idx}", 0.0)
        if len(series) == 2:
            slot["variance"] = flt(slot["s0"]) - flt(slot["s1"])
        if (any(abs(flt(slot.get(f"s{i}"))) >= 0.005 for i in range(len(series)))
                or filters.get("show_zero_values")):
            rows.append(slot)
    rows = _keep_ancestors(rows, [merged[k] for k in order])

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
    # When the aggregate was built, as the trial balance itself says: a trust
    # compared by company reads it, and it can lag the live ledger by a day.
    stamp = _(" · built {0}").format(min(built)[:16]) if built and src != "live" else ""
    message = _("<b>{0}</b> series &nbsp;·&nbsp; {1} &nbsp;·&nbsp; {2}").format(
        len(series), _("comparing by {0}").format(mode.lower()),
        (_("monthly aggregate") + stamp) if src == "aggregate" else
        ((_("mixed sources") + stamp) if src == "mixed" else _("live GL")))
    return columns, rows, message, None, None


def _keep_ancestors(kept, ordered):
    """``kept`` plus every group above a kept row, in ``ordered``'s order.

    A group whose balance nets to nil in every series (a receivable at 100
    beside an advance at -100) was dropped while the accounts under it stayed,
    so they printed under whatever group came before it."""
    by_key = {r["account"]: r for r in ordered}
    keep = {id(r) for r in kept}
    for r in kept:
        cur, guard = r, 0
        while cur.get("parent_account") and guard < 30:
            cur = by_key.get(cur["parent_account"])
            if not cur:
                break
            keep.add(id(cur))
            guard += 1
    return [r for r in ordered if id(r) in keep]


def _compare_key(row, view):
    if view == VIEW_PARTY:
        return f"{row.get('party_type')}::{row.get('party')}"
    return row.get("account")


def _comparison_columns(series, view):
    # Wide enough for "01-04-2026 to 31-03-2027" and for a crore figure: at
    # 150 both were cut off, and the datatable cuts without an ellipsis.
    label = _("Party") if view == VIEW_PARTY else _("Account")
    cols = [{"fieldname": "label", "label": label, "fieldtype": "Data",
             "width": 300}]
    for idx, (name, _cos, _f, _t) in enumerate(series):
        cols.append({"fieldname": f"s{idx}", "label": name,
                     "fieldtype": "Currency", "options": "currency",
                     "width": 215})
    if len(series) == 2:
        cols.append({"fieldname": "variance", "label": _("Variance"),
                     "fieldtype": "Currency", "options": "currency",
                     "width": 215})
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

    Runs ONE QUERY PER COMPANY and concatenates. Callers accumulate with
    ``+=`` on the group key, so splitting the work is arithmetically
    identical — and it is the difference between working and not.

    A single ``company IN (...)`` group-by across a trust is pathological
    here: six companies over a fiscal year exceeded 100 seconds and blew
    past gunicorn's 120s worker timeout, which surfaced to the user as a
    bare "Internal Server Error" with nothing in the Error Log, because
    the worker was killed rather than raising. Per company the WHERE hits
    the `company` index and each slice sorts in memory. Same lesson the
    aggregate rebuild learned, applied to the live path.
    """
    if not companies:
        return []

    out = []
    for company in _touched_companies(companies, filters):
        out.extend(_gl_aggregate_one(company, group_cols, filters, opening))
    return out


def _gl_aggregate_one(company, group_cols, filters, opening):
    params = {
        "company": company,
        "from_date": filters.from_date,
        "to_date": filters.to_date,
    }

    where = ["gle.company = %(company)s", "gle.is_cancelled = 0"]
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

    where.extend(_narrowing(filters, params))

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


# Filters that narrow the ledger to part of it. The monthly aggregate is kept
# per (month, company, account, party) and carries none of them.
_NARROWING_FILTERS = (("cost_center", "Cost Center"), ("project", "Project"),
                      ("party_type_filter", "Party Type"))


def _narrowing(filters, params):
    """WHERE clauses for the narrowing filters, filling ``params``.

    Shared by the slice and the carry-forward, so the computed row is what
    the fiscal-year reset removed from THIS slice, not from the whole ledger."""
    where = []
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
    return where


def _touched_companies(companies, filters):
    """The companies, in order, whose ledger a narrowing filter matches at all.

    A company with no row on the selected project or cost centre adds
    nothing to the slice or to the carry-forward, so leaving it out changes
    no figure. It is what keeps a Project filter usable on a trust: GL Entry
    has no index on project, so every per-company query reads that company's
    whole ledger, and 34 companies took 104s on the test ledger against
    gunicorn's 120s worker limit. One pass finds the companies that carry
    the project and only those are queried. Answers are kept per company on
    the request's filters; they do not depend on the dates."""
    params = {}
    where = _narrowing(filters, params)
    if not where or not companies:
        return list(companies)

    known = filters.get("_touched")
    if known is None:
        known = filters["_touched"] = {}
    unknown = [c for c in companies if c not in known]
    if unknown:
        params["companies"] = tuple(unknown)
        hit = set(frappe.db.sql_list(f"""
            SELECT DISTINCT gle.company FROM `tabGL Entry` gle
            WHERE gle.company IN %(companies)s
              AND gle.is_cancelled = 0
              AND {' AND '.join(where)}
        """, params))
        for c in unknown:
            known[c] = c in hit
    return [c for c in companies if known[c]]


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

    # The aggregate cannot narrow by these. Served from it anyway, the
    # filter was dropped without a word: a trust under a Cost Center filter
    # came back as its whole ledger, figure for figure.
    narrowed = [_(label) for key, label in _NARROWING_FILTERS if filters.get(key)]

    if wants_fast and not filters.get("force_live"):
        if narrowed:
            filters._source_note = _(
                "read from the live ledger: the monthly aggregate cannot "
                "filter by {0}").format(", ".join(narrowed))
        elif tb_aggregate.can_serve(companies, filters.from_date, filters.to_date):
            filters._source = "aggregate"
            filters._source_built_at = tb_aggregate.built_at()
            return tb_aggregate.fetch(companies, group_cols,
                                      filters.from_date, filters.to_date,
                                      filters.get("_pl_reset_date"))
        else:
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


# ── company columns ───────────────────────────────────────────────────
# With two or more companies selected every figure above is consolidated.
# "Company columns" keeps each company's own figure beside it: a row then
# carries ``cv``, a list index-aligned with the resolved companies (the page
# receives that list as ``companies``), each entry the six VALUE_FIELDS in
# order, or None where the company has nothing on that row. Lists rather
# than dicts keyed by company name: a 34-company trust has ~800 rows.

COMPANY_COLUMN_VIEWS = (VIEW_ACCOUNT, VIEW_PARTY)


def _company_columns(filters, companies):
    """Per-company figures were asked for and mean something here: two or
    more companies, in a view whose rows are shared across companies.

    Account -> Party lists each company's real accounts (one company per
    row) and By Company already has one row per company, so neither has a
    second company to put beside the first."""
    return (bool(filters.get("company_columns")) and len(companies) > 1
            and (filters.get("view") or VIEW_ACCOUNT) in COMPANY_COLUMN_VIEWS)


def _add_values(into, values):
    for f in VALUE_FIELDS:
        into[f] = flt(into.get(f)) + flt(values.get(f))


def _cv(per_company, companies):
    """``{company: values}`` -> the row's ``cv`` list, aligned with companies."""
    out = []
    for co in companies:
        v = per_company.get(co)
        out.append([round(flt(v[f]), 2) for f in VALUE_FIELDS]
                   if v and _has_value(v) else None)
    return out


def _cv_has_value(cv):
    return any(c and any(abs(x) >= 0.005 for x in c) for c in (cv or []))


def _total_row(rows, label, only_top_level=False):
    total = _blank_row()
    total.update({"account": f"'{label}'", "account_name": f"'{label}'",
                  "party": f"'{label}'", "company": f"'{label}'",
                  "is_total": 1, "indent": 0, "has_value": True})
    width = max((len(r["cv"]) for r in rows if r and r.get("cv")), default=0)
    sums = [[0.0] * len(VALUE_FIELDS) for _i in range(width)]
    for r in rows:
        if r.get("is_total"):
            continue
        if only_top_level and r.get("parent_account"):
            continue
        for f in VALUE_FIELDS:
            total[f] += flt(r.get(f))
        for i, c in enumerate(r.get("cv") or []):
            if c:
                for j, x in enumerate(c):
                    sums[i][j] += x
    if width:
        # Each company's own column, summed the way the consolidated one is:
        # its Opening and Closing come to that company's own difference.
        total["cv"] = [[round(x, 2) for x in s] if any(abs(x) >= 0.005 for x in s) else None
                       for s in sums]
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


# Separates a merge key from what splits it. A normalised name has no
# whitespace and an account number no control characters, so it never
# occurs inside a key of its own.
KEY_SEP = "\x1f"
# Marks the group of an account that is a group in one company and a ledger
# in another. Doubled, so no split by placement (key, separator, parent key)
# can arrive at it: no parent key starts with the separator.
GROUP_SUFFIX = KEY_SEP * 2 + "group"


def _merge_keys(accounts, companies):
    """``{real account name: row key}`` across several companies, and the keys
    split off by placement: ``{key: parent key}``.

    ``_merge_key`` folds the same account across companies by name or number.
    Two things then keep it apart again, because the colleges' charts have
    drifted:

    * An account that is a group in one company and a ledger in another
      (Secured Loans, on the dev data) is two rows. As one, hiding group
      accounts either dropped the ledger's balance or counted the group's
      children twice, and one college read out by 16.6 crore.
    * An account that companies file under different parents is a row per
      parent. The placement most companies share keeps the plain key; the
      others become their own rows under their own parents. Merged, the row
      followed whichever company was read last: one college filing
      Temporary Opening under Equity carried every college's Temporary
      Opening into Source of Funds, about 110 crore each on a ten-college
      trust, and no college's column matched its own trial balance.

    Split this way every row sits under one parent, every group is the sum of
    the rows under it, and each company's figures roll up exactly as in its
    own chart. Ties go to the company listed first."""
    rank = {co: i for i, co in enumerate(companies)}
    by_name = {a.name: a for a in accounts}
    keys = {a.name: _merge_key(a, True) for a in accounts}

    kinds = {}
    for a in accounts:
        kinds.setdefault(keys[a.name], set()).add(bool(a.is_group))
    for a in accounts:
        if a.is_group and len(kinds[keys[a.name]]) > 1:
            keys[a.name] += GROUP_SUFFIX

    ordered = sorted(accounts, key=lambda a: (rank.get(a.company, len(rank)), a.lft or 0))
    apart = {}
    # A split parent can split its children in turn, so repeat until nothing
    # moves; keys only ever get more specific, so this ends.
    for _guard in range(32):
        groups = {}
        for a in ordered:
            pk = keys.get(a.parent_account) if a.parent_account in by_name else None
            groups.setdefault(keys[a.name], {}).setdefault(pk, []).append(a)
        moved = False
        for k, by_parent in groups.items():
            if len(by_parent) < 2:
                continue
            moved = True
            keep = max(by_parent, key=lambda pk: len(by_parent[pk]))   # first-seen on ties
            for pk, accs in by_parent.items():
                if pk == keep:
                    continue
                nk = f"{k}{KEY_SEP}{pk or ''}"
                apart[nk] = pk
                for a in accs:
                    keys[a.name] = nk
        if not moved:
            break
    return keys, apart


def _build_by_account(filters, companies):
    multi = len(companies) > 1
    accounts = _account_master(companies)
    if not accounts:
        return []

    values = _slice(companies, ["account"], filters)
    # Company columns need no query of their own: the slice is keyed by REAL
    # account name, and every real account belongs to exactly one company.
    cocols = _company_columns(filters, companies)
    filters._company_columns = cocols

    # Fold per-company accounts onto their merge key.
    by_name = {a.name: a for a in accounts}
    if multi:
        keys, apart = _merge_keys(accounts, companies)
    else:
        keys, apart = {a.name: a.name for a in accounts}, {}
    nodes = {}
    for acc in accounts:
        k = keys[acc.name]
        node = nodes.get(k)
        if not node:
            node = nodes[k] = {
                "key": k,
                "account_name": (f"{acc.account_number} - {acc.account_name}"
                                 if acc.account_number else acc.account_name),
                "parent_key": None,
                "root_type": acc.root_type,
                "account_type": acc.account_type,
                "is_control": _is_control(acc.account_type, acc.account_name),
                "is_group": acc.is_group,
                "lft": acc.lft,
                "members": [],
                "member_companies": [],
                "co": {},
                **_blank_row(),
            }
        node["members"].append(acc.name)
        node["member_companies"].append(acc.company)
        if acc.parent_account:
            parent = by_name.get(acc.parent_account)
            if parent:
                # Every member of a row shares its parent: _merge_keys splits
                # the ones that do not.
                node["parent_key"] = keys[parent.name]

        v = values.get((acc.name,))
        if v:
            for f in VALUE_FIELDS:
                node[f] += flt(v[f])
            if cocols:
                _add_values(node["co"].setdefault(acc.company, _blank_row()), v)

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
            for co, v in node["co"].items():
                _add_values(nodes[pk]["co"].setdefault(co, _blank_row()), v)

    # A row split off by placement says where it sits, or two rows of one name
    # read as a duplicate once group accounts are hidden.
    for k, pk in apart.items():
        node = nodes.get(k)
        if node:
            parent = nodes.get(pk)
            node["account_name"] = (
                _("{0} (under {1})").format(node["account_name"], parent["account_name"])
                if parent else _("{0} (at the top)").format(node["account_name"]))

    show_net = filters.get("show_net_values")
    rows = []
    for node in _tree_order(nodes, depth):
        if show_net:
            _net_off(node, _natural_side(node["root_type"]))
            # Each company nets on its own: A's 100 Dr beside B's 40 Cr is not
            # "60 Dr in both".
            for v in node["co"].values():
                _net_off(v, _natural_side(node["root_type"]))
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
        if cocols:
            row["cv"] = _cv(node["co"], companies)
            # A merged account at 100 Dr in one college and 100 Cr in another
            # nets to nil consolidated, and is still two balances to show.
            row["has_value"] = row["has_value"] or _cv_has_value(row["cv"])

        # A control account can be opened in place to reveal the parties
        # behind it, so it carries the real account names it merges. Only
        # control accounts — attaching the member list to all 800 rows of a
        # 34-company trust would bloat the payload for no purpose.
        if node["is_control"] and not node["is_group"]:
            row["is_control"] = 1
            row["members"] = node["members"]
            # Which company each of those accounts is, so a party opened from
            # one company's column reaches that company's account, and a
            # combined row spanning several companies says so instead of
            # opening the first one's.
            row["member_companies"] = node["member_companies"]

        rows.append(row)

    rows = _apply_indent(rows)

    if not filters.get("show_group_accounts"):
        rows = [r for r in rows if not r.get("is_group_account")]
        for r in rows:
            r["indent"] = 0
            r["parent_account"] = None

    if not filters.get("show_zero_values"):
        rows = _drop_zero_keeping_ancestors(rows)

    if cocols:
        carry = _unclosed_pl_row_by_company(companies, filters,
                                            _company_currency(companies[0]))
    else:
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
    return _carry_row(_unclosed_pl_net(companies, filters), currency)


def _unclosed_pl_row_by_company(companies, filters, currency):
    """The same balancing line, with each company's share in its own column.

    Without it no company column ties: each college's balance sheet is short
    by its own unclosed prior-year result, exactly as By Company found. The
    consolidated figure is the sum of the shares — the live path computes it
    per company anyway. Shares can cancel (one college's loss, another's
    profit), so the line stays whenever any company has one."""
    shares = _unclosed_pl_shares(companies, filters)
    live = [s for s in shares.values() if abs(s) >= 0.005]
    if not live:
        return None
    net = sum(shares.values())
    # The shares cancel: nil consolidated, and still a figure in each column.
    row = _carry_row(net if abs(net) >= 0.005 else 1.0, currency)
    if abs(net) < 0.005:
        row.update(_blank_row())
    if any(s > 0 for s in live) and any(s < 0 for s in live):
        # One college's loss beside another's profit: "Accumulated Loss" over
        # a column reading Cr would be wrong for that college. Each cell's
        # Dr / Cr says which it is.
        row["account_name"] = _("Accumulated Profit / Loss b/f — P&L never closed")
    row["cv"] = _cv({co: _carry_values(s) for co, s in shares.items()}, companies)
    return row


def _unclosed_pl_shares(companies, filters):
    """``_unclosed_pl_net`` company by company: ``{company: net}``.

    From the same tier as the rest of the report. On the aggregate it is one
    grouped query rather than one per company; live, ``_unclosed_pl_net``
    already queries per company, so the arithmetic is the same either way."""
    reset = filters.get("_pl_reset_date")
    if not reset or not companies:
        return {}
    if filters.get("_source") == "aggregate":
        from dux_voucher.dux_voucher.api import tb_aggregate
        return {co: flt(net) for co, net in tb_aggregate.unclosed_pl(
            companies, filters.from_date, filters.to_date, reset,
            by_company=True).items()}
    return {co: flt(_unclosed_pl_net([co], filters))
            for co in _touched_companies(companies, filters)}


def _carry_values(net):
    """A signed carry (Dr-positive) as the six value fields of its row."""
    v = _blank_row()
    side = "debit" if net > 0 else "credit"
    v[f"opening_{side}"] = v[f"closing_{side}"] = abs(flt(net))
    return v


def _unclosed_pl_net(companies, filters):
    """The prior-year P&L the reset removed, signed Dr-positive (a loss is
    positive). 0.0 when the reset is off.

    Must run after _slice(): it reads the tier _slice() chose."""
    reset = filters.get("_pl_reset_date")
    if not reset or not companies:
        return 0.0

    # Take it from whichever tier served the rest of the report. Querying
    # live here while the balances came from the aggregate was measurably
    # worse than not having an aggregate at all — the fast path returned in
    # milliseconds and then this held the request open for ~40s.
    if filters.get("_source") == "aggregate":
        from dux_voucher.dux_voucher.api import tb_aggregate
        return flt(tb_aggregate.unclosed_pl(
            companies, filters.from_date, filters.to_date, reset))

    # Per company, for the same reason as _gl_aggregate: one IN-list
    # group-by across a trust is what blew the worker timeout.
    net = 0.0
    for company in _touched_companies(companies, filters):
        params = {"company": company, "from_date": filters.from_date,
                  "to_date": filters.to_date, "pl_reset": reset}
        # The slice's own narrowing: under a Cost Center filter this is that
        # cost centre's prior-year result, not the whole ledger's.
        narrow = "".join(f"\n              AND {w}" for w in _narrowing(filters, params))
        row = frappe.db.sql(f"""
            SELECT COALESCE(SUM(gle.debit), 0)  AS debit,
                   COALESCE(SUM(gle.credit), 0) AS credit
            FROM `tabGL Entry` gle
            JOIN `tabAccount` acc ON acc.name = gle.account
            WHERE gle.company = %(company)s
              AND gle.is_cancelled = 0
              AND acc.root_type IN ('Income', 'Expense')
              AND ( gle.posting_date < %(from_date)s
                    OR (gle.is_opening = 'Yes'
                        AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s) )
              AND gle.posting_date < %(pl_reset)s{narrow}
        """, params, as_dict=True)
        if row:
            net += flt(row[0].debit) - flt(row[0].credit)

    return net


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
    cocols = _company_columns(filters, companies)
    filters._company_columns = cocols
    if cocols:
        # The same slice with the company kept apart; the consolidated row is
        # its sum, as it is when the live path queries company by company.
        values, per_co = {}, {}
        for (pt, p, co), v in _slice(companies, ["party_type", "party", "company"],
                                     filters).items():
            _add_values(values.setdefault((pt, p), _blank_row()), v)
            _add_values(per_co.setdefault((pt, p), {}).setdefault(co, _blank_row()), v)
    else:
        values, per_co = _slice(companies, ["party_type", "party"], filters), {}
    show_net = filters.get("show_net_values")
    currency = _company_currency(companies[0])

    names = _resolve_party_names(
        {(pt, p) for (pt, p) in values.keys() if p})

    rows = []
    for (party_type, party), v in values.items():
        if not party:
            continue
        natural = "debit" if party_type == "Customer" else "credit"
        row = dict(v)
        if show_net:
            _net_off(row, natural)
        row.update({
            "party_type": party_type,
            "party": party,
            "party_name": names.get((party_type, party)) or party,
            "currency": currency,
            "indent": 0,
        })
        row["has_value"] = _has_value(row)
        if cocols:
            own = per_co.get((party_type, party)) or {}
            if show_net:
                for cv in own.values():
                    _net_off(cv, natural)
            row["cv"] = _cv(own, companies)
            # A supplier owed 100 by one college and owing 100 to another
            # nets to nil, and is still two balances.
            row["has_value"] = row["has_value"] or _cv_has_value(row["cv"])
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

    A plain account (not a control account) with no party on any line is
    listed without children: its only child would be an Unattributed row
    repeating its own figure.
    """
    values = _slice(companies, ["account", "party_type", "party"], filters)
    if not values:
        # Nothing in the period or the opening can still leave last year's
        # result to carry: a Project seen only on last year's expense lines.
        # By Account shows that carry, so this view must too.
        carry = (None if filters.get("control_accounts_only") else
                 _unclosed_pl_row(companies, filters, _company_currency(companies[0])))
        return [carry, _total_row([carry], _("Total"), only_top_level=True)] if carry else []

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
                not _is_control(meta.account_type, meta.account_name):
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

        # Under a plain account with no party on any line, the only child is
        # an Unattributed row repeating the account's own figure: 531 of them
        # on a seven-company trust in testing, burying the control accounts
        # this view exists for. Control accounts keep theirs (there it is the
        # point), and a plain account that does carry parties still opens.
        if meta and not _is_control(meta.account_type, meta.account_name) \
                and not any(p for _pt, p, _v in children):
            continue

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

    # The same balancing line By Account carries: P&L accounts' opening is
    # reset at the fiscal-year boundary, so without it this view read "out"
    # by the whole prior-year result. Not when only control accounts are
    # listed — a subset of the ledger was never going to tie.
    if not filters.get("control_accounts_only"):
        carry = _unclosed_pl_row(companies, filters, currency)
        if carry:
            rows.append(carry)

    rows.append(_total_row(rows, _("Total"), only_top_level=True))
    return rows


# ══════════════════════════════════════════════════════════════════════
# VIEW — BY COMPANY
# ══════════════════════════════════════════════════════════════════════

def _build_by_company(filters, companies):
    values = _slice(companies, ["company"], filters)
    show_net = filters.get("show_net_values")
    rows = []
    # Every company, not only the ones the slice returned. Under a Cost Center
    # or Project filter a college can have nothing in the period and nothing in
    # its opening (the reset took out last year's income and expense) and still
    # carry last year's result for that cost centre. By Account counts it, so
    # it needs a row here too, or the two views disagree by that amount.
    for company in companies:
        v = values.get((company,))
        carry = _unclosed_pl_net([company], filters)
        if v is None:
            if abs(carry) < 0.005:
                continue
            v = _blank_row()
        row = dict(v)
        # By Account balances the fiscal-year P&L reset with one computed
        # "Accumulated Loss/Profit b/f" row. A company row is that company's
        # whole ledger, so its own share of that line belongs inside it.
        # Without it every company read "out" by its own unclosed prior-year
        # result: hundreds of crores on a seven-company trust in testing,
        # where By Account showed only the ledger's real difference. Folded
        # into opening and closing on its own side, a company whose books tie
        # nets to nil and one that does not shows its real difference.
        if abs(carry) >= 0.005:
            side = "debit" if carry > 0 else "credit"
            row[f"opening_{side}"] = flt(row.get(f"opening_{side}")) + abs(carry)
            row[f"closing_{side}"] = flt(row.get(f"closing_{side}")) + abs(carry)
            row["carry_forward"] = carry
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

def _money(fieldname, label, width=165):
    # The datatable cuts a figure off without an ellipsis, so a short column
    # shows a different number. 130 lost the last digit of a college's crore
    # figures (135 px) and of most of a trust's (149 px); 165 holds anything
    # under 10,000 crore.
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
        if filters.get("view") == VIEW_PARTY:
            # Most of a ledger has no party, so a list of parties never ties:
            # its total is where the parties stand on balance, not an error.
            bits.append(_("net of parties {0}").format(_dr_cr(diff)))
        elif abs(diff) < 0.005:
            bits.append(_("<span style='color:#146B4A'>&#10003; tied</span>"))
        else:
            bits.append(_("<span style='color:#B3261E'>&#9888; out of balance "
                          "by {0}</span>").format(frappe.format_value(
                              diff, {"fieldtype": "Currency"})))

    # By Company folds each company's share into its own row instead.
    carry = next((r for r in data if r.get("is_computed") or r.get("carry_forward")), None)
    if carry:
        bits.append(_("<span style='color:#A65A00'>includes a computed "
                      "carry-forward — no Period Closing Voucher has been "
                      "run for {0}</span>").format(
                          _("this company") if len(companies) == 1 else _("these companies")))

    mism = [r for r in data if r.get("mismatch")]
    if mism:
        bits.append(_("<span style='color:#A65A00'>{0} party-type "
                      "mismatch(es)</span>").format(len(mism)))

    unatt = [r for r in data if r.get("is_unattributed")]
    if unatt:
        bits.append(_("{0} unattributed row(s)").format(len(unatt)))

    return "  &nbsp;·&nbsp;  ".join(bits)


def _dr_cr(net):
    """A signed Dr-positive figure as "₹ 1,234.00 Dr" / "Cr", or nil."""
    if abs(flt(net)) < 0.005:
        return _("nil")
    return "{0} {1}".format(frappe.format_value(abs(net), {"fieldtype": "Currency"}),
                            "Dr" if net > 0 else "Cr")


def _summary(data, filters):
    total = next((r for r in data if r.get("is_total")), None)
    if not total:
        return None
    diff = flt(total["closing_debit"]) - flt(total["closing_credit"])
    tied = abs(diff) < 0.005
    if filters.get("view") == VIEW_PARTY:
        last = {"label": _("Net of parties"), "value": diff, "datatype": "Currency",
                "indicator": "blue"}
    else:
        last = {"label": _("Difference"), "value": diff, "datatype": "Currency",
                "indicator": "green" if tied else "red"}
    return [
        {"label": _("Closing (Dr)"), "value": flt(total["closing_debit"]),
         "datatype": "Currency", "indicator": "blue"},
        {"label": _("Closing (Cr)"), "value": flt(total["closing_credit"]),
         "datatype": "Currency", "indicator": "blue"},
        last,
    ]
