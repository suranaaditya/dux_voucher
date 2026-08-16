"""Monthly aggregate for the Trial Balance fast path.

Why this exists, measured rather than assumed: on the dev ledger a single
company grouped by account returns in about a second, while all 69
companies takes 37.95s. Adding ``docstatus = 1`` to fit the site's existing
composite index made it *worse* — 76.75s — so index tuning is not the
answer. A wide multi-company trial balance simply cannot be computed
synchronously against 5,088,888 GL rows.

The shape chosen is monthly buckets rather than point-in-time snapshots.
A snapshot answers only the dates it was taken on; monthly buckets answer
any month-aligned range, and opening is just the sum of every earlier
bucket. The other app on this site (dux_groupview) stores daily snapshots,
which proves the general approach works at this scale but cannot answer
"April through August" without a scan.

Rows are keyed (company, period, account, party_type, party) so the same
table serves the account view, the party view and the cross-section.
"""

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime, add_months

AGG_DOCTYPE = "Dux TB Period Balance"


def month_key(d):
    d = getdate(d)
    return f"{d.year:04d}-{d.month:02d}"


def is_month_start(d):
    return getdate(d).day == 1


def is_month_end(d):
    d = getdate(d)
    nxt = add_months(d, 1)
    return getdate(nxt).day == 1 and (getdate(nxt) - d).days in (28, 29, 30, 31)


def range_is_month_aligned(from_date, to_date):
    """The aggregate can answer a range only when it begins on the first of
    a month and ends on the last. Anything else falls back to live GL, and
    the report says so rather than quietly returning a different period."""
    from_date, to_date = getdate(from_date), getdate(to_date)
    if not is_month_start(from_date):
        return False
    nxt = add_months(getdate(f"{to_date.year:04d}-{to_date.month:02d}-01"), 1)
    return (getdate(nxt) - to_date).days == 1


# ══════════════════════════════════════════════════════════════════════
# BUILD
# ══════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def rebuild(companies=None, from_period=None, to_period=None, commit=True):
    """(Re)build the aggregate.

    companies   list, or None for every company under a group company.
                Trust-wise by default: a company outside every trust always
                takes the live path, which for one company is about a
                second, so aggregating it would be wasted work.
    from_period / to_period  'YYYY-MM'. None means the full GL span.
    """
    if isinstance(companies, str):
        companies = frappe.parse_json(companies)
    companies = companies or _trust_companies()
    if not companies:
        return {"companies": 0, "rows": 0,
                "note": "no company sits under a group company"}

    started = now_datetime()

    # Built one company at a time, deliberately.
    #
    # The obvious implementation is a single GROUP BY over every company at
    # once. Measured on dev that never finished in five minutes: grouping
    # ~2.9M rows five ways, joined to Account, is a sort the optimiser has
    # no index for. Per company the WHERE hits the `company` index and each
    # slice is ~85k rows, which sorts in memory. Same output, and progress
    # is observable instead of being one opaque wait.
    #
    # root_type / account_type are attached from a Python dict rather than
    # joined, so the join disappears from the hot query entirely.
    acc_meta = {
        a.name: a for a in frappe.get_all(
            "Account", filters={"company": ["in", companies]},
            fields=["name", "root_type", "account_type"], limit=100000)
    }

    total_rows = 0
    for company in companies:
        params = {"company": company}
        where = ["gle.is_cancelled = 0", "gle.company = %(company)s"]
        if from_period:
            params["frm"] = f"{from_period}-01"
            where.append("gle.posting_date >= %(frm)s")
        if to_period:
            params["to"] = f"{to_period}-01"
            where.append("gle.posting_date < DATE_ADD(%(to)s, INTERVAL 1 MONTH)")

        rows = frappe.db.sql(f"""
            SELECT DATE_FORMAT(gle.posting_date, '%%Y-%%m') AS period,
                   gle.account                              AS account,
                   COALESCE(gle.party_type, '')             AS party_type,
                   COALESCE(gle.party, '')                  AS party,
                   COALESCE(SUM(CASE WHEN gle.is_opening='No'  THEN gle.debit  END),0) AS debit,
                   COALESCE(SUM(CASE WHEN gle.is_opening='No'  THEN gle.credit END),0) AS credit,
                   COALESCE(SUM(CASE WHEN gle.is_opening='Yes' THEN gle.debit  END),0) AS opening_debit,
                   COALESCE(SUM(CASE WHEN gle.is_opening='Yes' THEN gle.credit END),0) AS opening_credit
            FROM `tabGL Entry` gle
            WHERE {' AND '.join(where)}
            GROUP BY period, gle.account,
                     COALESCE(gle.party_type, ''), COALESCE(gle.party, '')
        """, params, as_dict=True)

        del_where = ["company = %(company)s"]
        if from_period:
            params["fp"] = from_period
            del_where.append("period >= %(fp)s")
        if to_period:
            params["tp"] = to_period
            del_where.append("period <= %(tp)s")
        frappe.db.sql(
            f"DELETE FROM `tab{AGG_DOCTYPE}` WHERE {' AND '.join(del_where)}",
            params)

        if rows:
            frappe.db.bulk_insert(
                AGG_DOCTYPE,
                fields=["name", "company", "period", "account", "party_type",
                        "party", "root_type", "account_type", "debit", "credit",
                        "opening_debit", "opening_credit"],
                values=[
                    (frappe.generate_hash(length=10), company, r.period, r.account,
                     r.party_type or None, r.party or None,
                     (acc_meta.get(r.account) or {}).get("root_type"),
                     (acc_meta.get(r.account) or {}).get("account_type"),
                     r.debit, r.credit, r.opening_debit, r.opening_credit)
                    for r in rows
                ],
                ignore_duplicates=True,
            )
            total_rows += len(rows)

        if commit:
            frappe.db.commit()

    _set_stamp(started)
    return {
        "companies": len(companies),
        "rows": total_rows,
        "seconds": round((now_datetime() - started).total_seconds(), 2),
    }


def _trust_companies():
    """Every ledger company that sits beneath a group company."""
    return frappe.db.sql_list("""
        SELECT c.name FROM `tabCompany` c
        WHERE c.is_group = 0 AND c.parent_company IS NOT NULL
              AND c.parent_company != ''
    """)


def rebuild_nightly(months_back=2):
    """Scheduler entry point — see hooks.py.

    Incremental on purpose. A full rebuild reads every GL row for every
    trust company and groups it five ways; on the dev ledger that is a
    multi-minute query over ~2.9M rows. Run nightly it would be pure waste,
    because history does not change — only the current month does, plus
    whatever late postings land in the one before it.

    Older buckets are only ever wrong if someone back-posts beyond the
    window, so a full rebuild stays available by hand (and from the report's
    own toolbar button) for the day that happens.
    """
    today = getdate(frappe.utils.nowdate())
    frm = month_key(add_months(today, -abs(months_back)))
    return rebuild(from_period=frm, to_period=month_key(today))


# ══════════════════════════════════════════════════════════════════════
# FRESHNESS
# ══════════════════════════════════════════════════════════════════════

_STAMP_KEY = "dux_tb_aggregate_built_at"


def _set_stamp(when):
    frappe.db.set_default(_STAMP_KEY, str(when))


def built_at():
    return frappe.db.get_default(_STAMP_KEY)


def coverage():
    """What the aggregate currently holds — used to decide whether the fast
    path can answer a given request at all."""
    row = frappe.db.sql(f"""
        SELECT COUNT(*) AS rows_, MIN(period) AS min_p, MAX(period) AS max_p,
               COUNT(DISTINCT company) AS companies
        FROM `tab{AGG_DOCTYPE}`
    """, as_dict=True)
    out = row[0] if row else frappe._dict()
    out["built_at"] = built_at()
    return out


# ══════════════════════════════════════════════════════════════════════
# READ
# ══════════════════════════════════════════════════════════════════════

def can_serve(companies, from_date, to_date):
    """True when the aggregate covers every company and the whole range.

    Deliberately strict. A reconciliation report that silently answers from
    a partially-populated aggregate is worse than one that takes 38s.
    """
    if not range_is_month_aligned(from_date, to_date):
        return False
    if not companies:
        return False

    covered = set(frappe.db.sql_list(
        f"SELECT DISTINCT company FROM `tab{AGG_DOCTYPE}`"))
    if not set(companies).issubset(covered):
        return False

    cov = coverage()
    if not cov.get("rows_"):
        return False
    # The aggregate must reach back far enough to compute opening, and
    # forward far enough to cover the period.
    return cov["max_p"] >= month_key(to_date)


def fetch(companies, group_cols, from_date, to_date, pl_reset_date=None):
    """The aggregate equivalent of the live GL slice.

    Returns {group tuple: {opening_debit, opening_credit, debit, credit}}
    with exactly the semantics the live path produces:
      opening = normal movement in every month before the period
                + every is_opening-flagged row up to the end of the period
      period  = normal movement inside the period
    """
    from_p, to_p = month_key(from_date), month_key(to_date)
    params = {"companies": tuple(companies), "from_p": from_p, "to_p": to_p}

    select = ", ".join(f"agg.{c} AS {c}" for c in group_cols)
    group = ", ".join(f"agg.{c}" for c in group_cols)

    # P&L opening resets at the fiscal-year boundary. Because buckets are
    # monthly and fiscal years start on the first of a month, the cut is
    # expressible as a period comparison with no date arithmetic.
    pl_clause = ""
    if pl_reset_date:
        params["pl_p"] = month_key(pl_reset_date)
        pl_clause = ("AND (agg.root_type NOT IN ('Income','Expense') "
                     "     OR agg.period >= %(pl_p)s)")

    rows = frappe.db.sql(f"""
        SELECT {select},
               COALESCE(SUM(CASE WHEN agg.period < %(from_p)s {pl_clause}
                                 THEN agg.debit  END), 0)
             + COALESCE(SUM(CASE WHEN agg.period <= %(to_p)s {pl_clause}
                                 THEN agg.opening_debit  END), 0) AS opening_debit,
               COALESCE(SUM(CASE WHEN agg.period < %(from_p)s {pl_clause}
                                 THEN agg.credit END), 0)
             + COALESCE(SUM(CASE WHEN agg.period <= %(to_p)s {pl_clause}
                                 THEN agg.opening_credit END), 0) AS opening_credit,
               COALESCE(SUM(CASE WHEN agg.period BETWEEN %(from_p)s AND %(to_p)s
                                 THEN agg.debit  END), 0) AS debit,
               COALESCE(SUM(CASE WHEN agg.period BETWEEN %(from_p)s AND %(to_p)s
                                 THEN agg.credit END), 0) AS credit
        FROM `tab{AGG_DOCTYPE}` agg
        WHERE agg.company IN %(companies)s
        GROUP BY {group}
    """, params, as_dict=True)

    out = {}
    for r in rows:
        key = tuple(r.get(c) or None for c in group_cols)
        out[key] = {
            "opening_debit": r.opening_debit,
            "opening_credit": r.opening_credit,
            "debit": r.debit,
            "credit": r.credit,
            "closing_debit": r.opening_debit + r.debit,
            "closing_credit": r.opening_credit + r.credit,
        }
    return out
