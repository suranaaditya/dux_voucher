"""Backend for the Capital Projects dashboard.

**Everything here is computed from ``tabGL Entry``, not from Project's own
costing fields.** That is a deliberate decision, and the reasons matter:

* ``Project.total_purchase_cost`` reads ``Purchase Invoice Item.project``
  and nothing else — Purchase Orders and Purchase Receipts contribute zero.
* It is maintained by incremental delta arithmetic on PI submit/cancel via
  ``db_set``, bypassing validate. An amendment, a direct edit or a failed
  job leaves it permanently skewed.
* The only from-scratch reconcile job early-returns when Selling Settings
  has ``sales_update_frequency == 'Each Transaction'`` — the common config.
* Nothing on Project rolls up GL at all, so money spent through the Dux
  Payment Voucher would never appear.

GL Entry is the one place every document type lands with ``project``
already populated, because ERPNext's ``get_gl_dict`` seeds each row with
``doc.get("project")``.

**Committed is the deliberate exception.** It comes from Purchase Orders,
which never post to the ledger, so it is a forecast rather than an
accounting figure. The page labels it as such.

Queries run **per company**. A single wide ``company IN (...)`` GROUP BY
over this site's GL takes 38-77s at 69 companies and blows gunicorn's 120s
worker timeout — see CLAUDE.md §9. The arithmetic is identical either way.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, add_months


# The roles the Page itself is gated on. Gating the Page record hides the
# dashboard from the menu; it does not stop anyone POSTing to these
# endpoints directly, so the check has to live where the data is served.
# The Trial Balance in this app learned that first — see
# trial_balance.require_access — and this is the same pattern.
DASHBOARD_ROLES = {
    "System Manager",
    "Accounts Manager",
    "Accounts User",
    "Projects Manager",
    "Projects User",
}


def require_access():
    """Refuse anyone who could not open the page itself.

    Without this, any authenticated account on the site — including a portal
    user with no roles at all, which on an institutional ERP means students,
    parents and vendors — can read the whole group's capital spend.
    """
    if set(frappe.get_roles()) & DASHBOARD_ROLES:
        return
    frappe.throw(
        _("You do not have access to Capital Projects. Ask an administrator "
          "for the 'Projects User' role."),
        frappe.PermissionError)


# GL rows with no project are bucketed under this sentinel so one grouped
# query can serve both the per-project figures and the unattributed total.
NO_PROJECT = "\x00none"

# Accounts that represent the project's own cost. Bank/cash is the payment
# side and party accounts are settlement — neither is a cost.
#
# The Asset side is deliberately a WHITELIST rather than "everything that is
# not a bank or a party account". Measured on production: 17,735 non-group
# Asset ledgers carry a BLANK account_type, and the largest of them are
# inter-company and Branch & Division accounts holding 126, 104 and 81 crore.
# Under the old rule a single mis-tagged inter-company transfer would have
# reported a hundred crore of project cost. Every Asset account our own
# projects book to is properly typed (Capital Work in Progress, Fixed Asset),
# and blank-typed accounts we rely on are all root_type Expense, where blank
# is normal and unambiguous.
#
# Anything the whitelist sets aside is REPORTED, not silently dropped — see
# _COST_LOOSE_SQL and the "set_aside" figure.
_CAPITAL_ASSET_TYPES = (
    "Capital Work in Progress",
    "Fixed Asset",
    "Stock",
    "Asset Received But Not Billed",
    "Expenses Included In Asset Valuation",
)
_COST_SQL = """
    CASE WHEN (acc.root_type = 'Expense'
               OR (acc.root_type = 'Asset'
                   AND acc.account_type IN {capital}))
          AND COALESCE(acc.account_type, '') NOT IN
              ('Bank', 'Cash', 'Receivable', 'Payable')
         THEN gle.debit - gle.credit ELSE 0 END
""".format(capital=str(_CAPITAL_ASSET_TYPES))

# The rule as it stood before the whitelist. Kept only so the difference can
# be surfaced: cost that looks like project spend but sits on an untyped
# Asset ledger is a tagging mistake worth seeing, not worth hiding.
_COST_LOOSE_SQL = """
    CASE WHEN acc.root_type IN ('Expense', 'Asset')
          AND COALESCE(acc.account_type, '') NOT IN
              ('Bank', 'Cash', 'Receivable', 'Payable')
         THEN gle.debit - gle.credit ELSE 0 END
"""
# Paid is read off the PAYABLE side, not the bank side, and that is
# deliberate. A Payment Voucher in Party + Head mode nets several parties
# into ONE bank credit row, so that row cannot belong to a single project —
# measured on real data, 75.4 lakh of bank movement was necessarily
# untagged while every supplier debit carried its own project correctly.
# Debits on a payable account are supplier settlements; credits are the
# invoices raising the liability, so only the debit side is "paid".
_PAID_SQL = """
    CASE WHEN COALESCE(acc.account_type, '') = 'Payable'
         THEN gle.debit ELSE 0 END
"""


# =====================================================================
# Entry point
# =====================================================================

@frappe.whitelist()
def get_dashboard(companies=None, from_date=None, to_date=None, status=None):
    """One payload for the whole dashboard.

    ``companies`` may be a list or a JSON string (Frappe passes either).
    Empty means group-wide — every company the user may see — because that
    is the view the client asked to land on.
    """
    require_access()
    permitted = _permitted_companies()
    selected = _parse_companies(companies)
    companies = _resolve_companies(selected, permitted)
    if not companies:
        return _empty()

    from_date, to_date = _resolve_period(from_date, to_date)

    projects = _project_master(companies, status)

    # Only scan companies that actually have projects. A company with none
    # can contribute nothing: its GL has no project to attribute to, and
    # "unattributed" is defined relative to accounts that tagged projects
    # use, so it has no such accounts either.
    #
    # This is not a micro-optimisation. Scanning all 69 companies over a
    # wide date range took 69.8s measured on dev — inside gunicorn's 120s
    # worker timeout, but only just, and unusable for a dashboard. Scoping
    # to the companies that hold projects cuts the loop to the handful that
    # can possibly matter.
    scan = [c for c in companies if c in {p["company"] for p in projects.values()}]

    gl = {}
    payable = {}
    unattributed = 0.0
    unattributed_rows = 0
    # Cost that the old, looser rule would have counted but the Asset
    # whitelist sets aside — a tagging mistake worth surfacing.
    set_aside = 0.0
    # Whether "unattributed" is even measurable. It is defined relative to
    # the accounts that TAGGED projects use, so a company with projects but
    # no tagging has nothing to measure against and would otherwise report a
    # confident zero. See _kpis.
    measurable = False

    for company in scan:
        payable.update(_payable_by_party(company, None, to_date))
        rows = _gl_for_company(company, from_date, to_date)
        used_accounts = {
            r["account"] for r in rows if r["project"] != NO_PROJECT
        }
        if used_accounts:
            measurable = True
        for r in rows:
            if r["project"] == NO_PROJECT:
                # Only count untagged spend on accounts that tagged projects
                # actually use. Without that restriction this would sweep in
                # salaries and every other expense and mean nothing.
                if r["account"] in used_accounts and abs(flt(r["cost"])) > 0.005:
                    unattributed += flt(r["cost"])
                    unattributed_rows += int(r["entries"] or 0)
                continue
            agg = gl.setdefault(r["project"], {
                "cost": 0.0, "paid": 0.0, "period_cost": 0.0,
                "period_paid": 0.0, "entries": 0, "last_activity": None
            })
            agg["cost"] += flt(r["cost"])
            agg["paid"] += flt(r["paid"])
            set_aside += flt(r["loose_cost"]) - flt(r["cost"])
            agg["period_cost"] += flt(r["period_cost"])
            agg["period_paid"] += flt(r["period_paid"])
            agg["entries"] += int(r["entries"] or 0)
            if r["last_activity"] and (
                not agg["last_activity"] or r["last_activity"] > agg["last_activity"]
            ):
                agg["last_activity"] = r["last_activity"]

    rows = _assemble(projects, gl,
                     _commitments(companies, projects.keys(), as_at=to_date))
    parties = _party_rows(
        {n: p["company"] for n, p in projects.items()},
        _party_commitments(companies, projects.keys(), as_at=to_date), payable)

    return {
        "period": {"from_date": str(from_date), "to_date": str(to_date)},
        "companies": scan,
        "companies_searched": len(companies),
        "companies_permitted": len(permitted) or len(companies),
        "scoped": bool(selected),
        "kpi": _kpis(rows, unattributed, unattributed_rows, measurable, set_aside),
        "projects": rows,
        "by_company": _by_company(rows),
        "parties": parties[:12],
        "parties_total": len(parties),
        "party_totals": _party_totals(parties, sum(r["invoiced"] for r in rows)),
        "attention": _attention(rows, unattributed, unattributed_rows,
                                measurable, set_aside),
        "generated_on": frappe.utils.now(),
    }


@frappe.whitelist()
def search_companies(txt=None, limit=25):
    """Companies for the dashboard's picker — only ones that hold a project.

    Deliberately not every company on the site. Three of this site's
    sixty-nine hold a project, so a picker listing all of them is a
    haystack in which sixty-six of the choices render an empty dashboard.
    One grouped read of ``tabProject`` gives both the list and the counts
    that make each option worth picking.

    Permission-scoped here as well as in ``get_dashboard`` — a whitelisted
    endpoint is reachable directly, whatever the picker offers.
    """
    require_access()
    permitted = set(_permitted_companies())
    like = "%{0}%".format(txt or "")

    rows = frappe.db.sql(
        """
        SELECT p.company                                   AS value,
               COUNT(*)                                    AS projects,
               SUM(CASE WHEN p.status = 'Open' THEN 1 ELSE 0 END) AS open_projects
        FROM `tabProject` p
        INNER JOIN `tabCompany` c ON c.name = p.company
        WHERE p.company LIKE %(l)s OR c.abbr LIKE %(l)s
        GROUP BY p.company
        ORDER BY projects DESC, p.company
        LIMIT %(lim)s
        """,
        {"l": like, "lim": int(limit)},
        as_dict=True,
    )

    return [{
        "value": r["value"],
        "projects": int(r["projects"] or 0),
        "open_projects": int(r["open_projects"] or 0),
    } for r in rows if not permitted or r["value"] in permitted]


# =====================================================================
# Sources
# =====================================================================

def _gl_for_company(company, from_date, to_date):
    """One grouped query per company, keyed on (project, account).

    Returns figures on TWO bases from a single pass:

    * ``cost`` / ``paid`` are **project to date** — everything up to
      ``to_date``, with no lower bound. That is the only basis on which
      "against estimate" means anything. A capital project runs for years,
      and Committed comes from purchase and work orders, which carry no
      period at all — so reading a twelve-month Invoiced against an
      all-time Committed was comparing two different windows.
    * ``period_cost`` / ``period_paid`` are the movement inside
      ``from_date .. to_date``, for the "in this window" line.

    Dropping the lower bound costs nothing here: measured on dev, the three
    companies that hold projects carry 76, 34 and 291 live GL rows, and the
    unbounded scan came back faster than the bounded one.

    Grouping on account as well as project is what lets the caller work
    out which accounts projects actually use, so the unattributed figure
    can be restricted to those same accounts — from the same single pass.

    ``is_cancelled = 0`` alone is sufficient here. Measured across
    5,088,888 GL rows on this site: zero live rows have a cancelled parent,
    and the reversal carries the ORIGINAL posting date, so cancelling a
    back-dated voucher today never leaks into today. CLAUDE.md §9.
    """
    return frappe.db.sql(
        """
        SELECT COALESCE(NULLIF(gle.project, ''), %(none)s) AS project,
               gle.account                                  AS account,
               SUM({cost})                                  AS cost,
               SUM({loose})                                 AS loose_cost,
               SUM({paid})                                  AS paid,
               SUM(CASE WHEN gle.posting_date >= %(from_date)s
                        THEN {cost} ELSE 0 END)             AS period_cost,
               SUM(CASE WHEN gle.posting_date >= %(from_date)s
                        THEN {paid} ELSE 0 END)             AS period_paid,
               COUNT(*)                                     AS entries,
               MAX(gle.posting_date)                        AS last_activity
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s
          AND gle.is_cancelled = 0
          AND gle.posting_date <= %(to_date)s
        GROUP BY project, gle.account
        """.format(cost=_COST_SQL, loose=_COST_LOOSE_SQL, paid=_PAID_SQL),
        {
            "company": company,
            "from_date": from_date,
            "to_date": to_date,
            "none": NO_PROJECT,
        },
        as_dict=True,
    )


def _commitments(companies, project_names, as_at=None):
    """What is on order against each project — ``{project: {po, wo, total}}``.

    Document-derived, NOT from GL: neither a Purchase Order nor a Work Order
    Contract posts a ledger entry. That is why Committed is labelled a
    forecast on the page.

    ``as_at`` bounds both sides on their own date field, so Committed is a
    to-date figure like Invoiced and Paid. Without it, moving the as-at date
    back left Committed at its all-time value and "% of estimate" compared
    an all-time numerator against a to-date denominator.

    One function so the portfolio table and the drill-down cannot disagree
    about what Committed means — both read this.
    """
    po_cutoff = "AND po.transaction_date <= %(as_at)s" if as_at else ""
    wo_cutoff = "AND wo_date <= %(as_at)s" if as_at else ""
    out = {}
    if not project_names:
        return out

    def bucket(name):
        return out.setdefault(name, {
            "po": {"count": 0, "value": 0.0},
            "wo": {"count": 0, "value": 0.0},
            "total": 0.0,
        })

    # Purchase Orders. Item-level project wins over the header, mirroring
    # ERPNext's own dimension precedence. The PO tables are small enough
    # that one query across companies is fine; the per-company loop exists
    # for GL.
    for r in frappe.db.sql(
        """
        SELECT COALESCE(NULLIF(poi.project, ''), po.project) AS project,
               SUM(poi.base_amount)                          AS value,
               COUNT(DISTINCT po.name)                       AS orders
        FROM `tabPurchase Order Item` poi
        INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
        WHERE po.docstatus = 1
          AND po.status NOT IN ('Closed', 'Cancelled')
          AND po.company IN %(companies)s
          AND COALESCE(NULLIF(poi.project, ''), po.project) IN %(projects)s
          {po_cutoff}
        GROUP BY project
        """.format(po_cutoff=po_cutoff),
        {"companies": tuple(companies), "projects": tuple(project_names),
         "as_at": as_at},
        as_dict=True,
    ):
        if not r["project"]:
            continue
        b = bucket(r["project"])
        b["po"] = {"count": int(r["orders"] or 0), "value": flt(r["value"])}

    # Work Order Contracts from the dux_civil_works app. For a construction
    # group the work orders ARE the commitment: on the seeded Nemani project
    # they are 93 lakh against 10 lakh of purchase orders, so a Committed
    # figure built from POs alone understates it by an order of magnitude.
    #
    # ``total_amount`` is the pre-tax line total — that app carries the taxed
    # figure separately in ``total_amount_with_tax``. Kept consistent with
    # their own document totals rather than quietly grossing it up here.
    #
    # Guarded on the doctype existing, so this app does not hard-depend on
    # dux_civil_works being installed.
    if frappe.db.exists("DocType", "Work Order Contract"):
        for r in frappe.db.sql(
            """
            SELECT project, SUM(total_amount) AS value, COUNT(*) AS contracts
            FROM `tabWork Order Contract`
            WHERE docstatus = 1
              AND company IN %(companies)s
              AND project IN %(projects)s
              {wo_cutoff}
            GROUP BY project
            """.format(wo_cutoff=wo_cutoff),
            {"companies": tuple(companies), "projects": tuple(project_names),
             "as_at": as_at},
            as_dict=True,
        ):
            if not r["project"]:
                continue
            b = bucket(r["project"])
            b["wo"] = {"count": int(r["contracts"] or 0), "value": flt(r["value"])}

    for b in out.values():
        b["total"] = flt(b["po"]["value"] + b["wo"]["value"])
    return out


def _project_master(companies, status=None):
    filters = {"company": ["in", companies]}
    if status and status != "All":
        filters["status"] = status

    out = {}
    for p in frappe.get_all(
        "Project",
        filters=filters,
        fields=["name", "project_name", "company", "status",
                "estimated_costing", "expected_start_date",
                "expected_end_date"],
        limit=2000,
    ):
        out[p.name] = p
    return out


# =====================================================================
# Assembly
# =====================================================================

def _assemble(projects, gl, committed):
    rows = []
    for name, p in projects.items():
        agg = gl.get(name) or {}
        invoiced = flt(agg.get("cost"))
        paid = flt(agg.get("paid"))
        est = flt(p.get("estimated_costing"))
        com = flt((committed.get(name) or {}).get("total"))

        rows.append({
            "name": name,
            "project_name": p.get("project_name") or name,
            "company": p.get("company"),
            "status": p.get("status"),
            "estimated": est,
            "committed": com,
            "invoiced": invoiced,
            "paid": paid,
            "outstanding": flt(invoiced - paid),
            "period_invoiced": flt(agg.get("period_cost")),
            "period_paid": flt(agg.get("period_paid")),
            "uninvoiced": flt(com - invoiced) if com else 0.0,
            "pct_of_estimate": flt(com / est * 100) if est else None,
            "entries": int(agg.get("entries") or 0),
            "last_activity": str(agg["last_activity"]) if agg.get("last_activity") else None,
            "expected_start_date": str(p["expected_start_date"]) if p.get("expected_start_date") else None,
            "expected_end_date": str(p["expected_end_date"]) if p.get("expected_end_date") else None,
        })

    # Biggest liability first — an executive reads top-down and stops.
    rows.sort(key=lambda r: (-r["outstanding"], -r["invoiced"]))
    return rows


def _kpis(rows, unattributed, unattributed_rows, measurable=True, set_aside=0.0):
    committed = sum(r["committed"] for r in rows)
    invoiced = sum(r["invoiced"] for r in rows)
    paid = sum(r["paid"] for r in rows)
    return {
        "committed": flt(committed),
        "invoiced": flt(invoiced),
        "paid": flt(paid),
        "outstanding": flt(invoiced - paid),
        "period_invoiced": flt(sum(r["period_invoiced"] for r in rows)),
        "period_paid": flt(sum(r["period_paid"] for r in rows)),
        "uninvoiced": flt(committed - invoiced),
        "unattributed": flt(unattributed),
        "unattributed_entries": unattributed_rows,
        # False means "nothing is tagged yet, so there is nothing to measure
        # untagged spend against" — NOT "no untagged spend". The two look
        # identical as a zero and are opposite in meaning.
        "unattributed_measurable": bool(measurable),
        # Cost on untyped Asset ledgers that the whitelist excluded.
        "set_aside": flt(set_aside),
        "active_projects": sum(1 for r in rows if r["status"] == "Open"),
        "total_projects": len(rows),
    }


def _by_company(rows):
    agg = {}
    for r in rows:
        a = agg.setdefault(r["company"], {
            "company": r["company"], "invoiced": 0.0,
            "paid": 0.0, "projects": 0,
        })
        a["invoiced"] += r["invoiced"]
        a["paid"] += r["paid"]
        a["projects"] += 1
    out = sorted(agg.values(), key=lambda a: -a["invoiced"])
    return out


def _attention(rows, unattributed, unattributed_rows, measurable=True, set_aside=0.0):
    """The exception list — what someone should actually act on."""
    today = getdate(nowdate())
    stale_before = add_months(today, -3)
    items = []

    for r in rows:
        if r["pct_of_estimate"] is not None and r["pct_of_estimate"] > 100:
            items.append({
                "kind": "OVER",
                "project": r["name"],
                "title": r["project_name"],
                "detail": _("Committed {0} against an estimate of {1} — {2}%").format(
                    _money(r["committed"]), _money(r["estimated"]),
                    int(r["pct_of_estimate"])),
            })

        if r["last_activity"] and getdate(r["last_activity"]) < stale_before \
                and r["status"] == "Open":
            days = (today - getdate(r["last_activity"])).days
            items.append({
                "kind": "STALLED",
                "project": r["name"],
                "title": r["project_name"],
                "detail": _("No ledger activity in {0} days").format(days),
            })

        if r["committed"] and not r["invoiced"]:
            items.append({
                "kind": "NOT BILLED",
                "project": r["name"],
                "title": r["project_name"],
                "detail": _("{0} ordered, nothing invoiced yet").format(
                    _money(r["committed"])),
            })

    if not measurable:
        items.insert(0, {
            "kind": "NOT MEASURED",
            "project": None,
            "title": _("Untagged spend cannot be measured yet"),
            "detail": _("Nothing carries a project, so there is no basis to "
                        "compare untagged spend against. This is not the same "
                        "as having none."),
        })

    if set_aside and abs(set_aside) > 0.005:
        items.insert(0, {
            "kind": "SET ASIDE",
            "project": None,
            "title": _("{0} tagged to a project on an untyped asset ledger")
                     .format(_money(set_aside)),
            "detail": _("Excluded from Invoiced. Inter-company and branch "
                        "accounts carry no account type, so this is usually a "
                        "tagging mistake rather than project cost."),
        })

    if unattributed > 0.005:
        items.insert(0, {
            "kind": "UNTAGGED",
            "project": None,
            "title": _("{0} with no project").format(_money(unattributed)),
            "detail": _("{0} ledger entries on accounts your projects use")
                      .format(unattributed_rows),
        })

    return items[:25]


# =====================================================================
# Helpers
# =====================================================================

def _money(v):
    return frappe.utils.fmt_money(flt(v), currency="INR")


def _permitted_companies():
    from dux_voucher.dux_voucher.api.reports_api import get_permitted_companies

    return get_permitted_companies() or []


def _parse_companies(companies):
    """Frappe hands a list through as a JSON string over HTTP."""
    if isinstance(companies, str):
        import json
        try:
            companies = json.loads(companies)
        except ValueError:
            companies = [companies] if companies else []
    return [c for c in (companies or []) if c]


def _resolve_companies(companies, permitted=None):
    """Company scoping is enforced here, not by narrowing the picker — a
    whitelisted endpoint is reachable directly."""
    companies = _parse_companies(companies)
    if permitted is None:
        permitted = _permitted_companies()

    if not companies:
        return permitted
    if not permitted:
        return companies
    return [c for c in companies if c in permitted]


def _resolve_period(from_date, to_date):
    to_date = getdate(to_date) if to_date else getdate(nowdate())
    from_date = getdate(from_date) if from_date else getdate(add_months(to_date, -12))
    if from_date > to_date:
        frappe.throw(_("From Date cannot be after To Date."))
    return from_date, to_date


def _empty():
    return {
        "period": {}, "companies": [],
        "companies_searched": 0, "companies_permitted": 0, "scoped": False,
        "kpi": {"committed": 0, "invoiced": 0, "paid": 0, "outstanding": 0,
                "period_invoiced": 0, "period_paid": 0,
                "uninvoiced": 0, "unattributed": 0, "unattributed_entries": 0,
                "unattributed_measurable": False, "set_aside": 0,
                "active_projects": 0, "total_projects": 0},
        "projects": [], "by_company": [], "attention": [],
        "parties": [], "parties_total": 0,
        "party_totals": {"ordered": 0, "billed": 0, "paid": 0, "owed": 0,
                         "advance": 0, "cost_without_party": 0},
        "generated_on": frappe.utils.now(),
    }


# =====================================================================
# Drill-down
# =====================================================================

@frappe.whitelist()
def get_project_detail(project, from_date=None, to_date=None):
    """One project, opened up: where the money stands against the estimate,
    how far each document stage has run, which heads it landed on, and the
    documents themselves.

    Every figure here is computed the same way as the portfolio row it was
    clicked from — the same ``_COST_SQL`` / ``_PAID_SQL`` expressions and the
    same ``_commitments`` reader — so the two surfaces cannot disagree.
    """
    require_access()
    p = frappe.db.get_value(
        "Project", project,
        ["name", "project_name", "company", "status", "project_type",
         "estimated_costing", "expected_start_date", "expected_end_date"],
        as_dict=True,
    )
    if not p:
        frappe.throw(_("Project {0} not found").format(project))
    _resolve_companies([p.company]) or frappe.throw(
        _("You do not have access to {0}.").format(p.company),
        frappe.PermissionError)

    from_date, to_date = _resolve_period(from_date, to_date)

    accounts = frappe.db.sql(
        """
        SELECT gle.account,
               SUM({cost}) AS amount
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s AND gle.project = %(project)s
          AND gle.is_cancelled = 0
          AND gle.posting_date <= %(to_date)s
        GROUP BY gle.account
        HAVING amount <> 0
        ORDER BY amount DESC
        """.format(cost=_COST_SQL),
        {"company": p.company, "project": project,
         "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    # Every voucher up to the as-at date. The summary is project-to-date —
    # a capital project runs for years and Committed carries no period, so
    # a twelve-month Invoiced read against an all-time Committed was
    # comparing two different windows. The date range still governs which
    # documents count as recent activity.
    vouchers = _project_vouchers(p.company, project, None, to_date)
    in_window = [v for v in vouchers if v["posting_date"] >= str(from_date)]

    # Totalled from the very rows the document list is drawn from, so the
    # summary can never claim something the list below it does not support.
    invoiced = flt(sum(v["cost"] for v in vouchers))
    paid = flt(sum(v["paid"] for v in vouchers))

    commitment = _commitments([p.company], [project], as_at=to_date).get(project) or {
        "po": {"count": 0, "value": 0.0},
        "wo": {"count": 0, "value": 0.0},
        "total": 0.0,
    }
    committed = flt(commitment["total"])
    estimated = flt(p.get("estimated_costing"))

    return {
        "project": {
            "name": p.name,
            "project_name": p.project_name or p.name,
            "company": p.company,
            "status": p.status,
            "project_type": p.project_type,
            "expected_start_date": str(p.expected_start_date) if p.expected_start_date else None,
            "expected_end_date": str(p.expected_end_date) if p.expected_end_date else None,
        },
        "period": {"from_date": str(from_date), "to_date": str(to_date)},
        "totals": {
            "estimated": estimated,
            "committed": committed,
            "invoiced": invoiced,
            "paid": paid,
            "outstanding": flt(invoiced - paid),
            "uninvoiced": flt(committed - invoiced) if committed else 0.0,
            "pct_of_estimate": flt(committed / estimated * 100) if estimated else None,
        },
        "period_totals": {
            "invoiced": flt(sum(v["cost"] for v in in_window)),
            "paid": flt(sum(v["paid"] for v in in_window)),
            "documents": len(in_window),
        },
        "chain": _chain(p.company, project, commitment, vouchers, as_at=to_date),
        "parties": _project_parties(p.company, project, from_date, to_date,
                                    invoiced, as_at=to_date),
        "work_orders": _work_order_billing(p.company, project, as_at=to_date),
        "accounts": [{"account": r["account"], "amount": flt(r["amount"])}
                     for r in accounts],
        "recent": in_window[:40],
        "recent_total": len(in_window),
        "documents_to_date": len(vouchers),
        "generated_on": frappe.utils.now(),
    }


def _project_parties(company, project, from_date, to_date, invoiced, as_at=None):
    """The party block for one project — the donut, the bars and the table.

    ``work_orders`` and ``purchase_orders`` are split out because they read
    very differently: the work orders are a handful of large contracts and
    make a legible donut, while the purchase orders are a long tail of small
    suppliers that a pie would render as invisible slivers.
    """
    rows = _party_rows(
        {project: company},
        _party_commitments([company], [project], as_at=as_at),
        _payable_by_party(company, None, to_date, project=project),
    )

    def ranked(key):
        out = [{"party": r["party"], "value": r[key]} for r in rows if r[key] > 0.005]
        out.sort(key=lambda x: -x["value"])
        return out

    return {
        "rows": rows,
        "work_orders": ranked("wo"),
        "purchase_orders": ranked("po"),
        "totals": _party_totals(rows, invoiced),
    }


# What each document type is called in the drill-down's list. The parent Dux
# voucher wins over the Payment Entry or Journal Entry it posted, because the
# parent is the document the operator actually made.
_KIND = {
    "Payment Voucher": "Payment",
    "Receipt Voucher": "Receipt",
    "Ex Student Receipt": "Receipt",
    "Ex Student Refund": "Refund",
    "Ex Student Writeoff": "Writeoff",
    "Student Fee Receipt": "Receipt",
    "Student Fee Refund": "Refund",
    "Inter-Company Transfer": "Transfer",
    "Purchase Invoice": "Invoice",
    "Purchase Receipt": "Receipt",
    "Purchase Order": "Order",
    "Payment Entry": "Payment",
    "Journal Entry": "Journal",
    "Stock Entry": "Stock",
    "Sales Invoice": "Sales",
}


def _project_vouchers(company, project, from_date, to_date):
    """Every voucher touching the project, one row each, newest first.

    ``from_date`` may be None for a project-to-date read.

    Resolves the Dux parent voucher behind a backend Payment Entry or
    Journal Entry, so a row opens ``PV-2026-00034`` rather than the
    ``ACC-JV-2026-08564`` it happened to post — the same
    ``custom_source_voucher`` idiom the ledger pages use.
    """
    rows = frappe.db.sql(
        """
        SELECT gle.posting_date,
               gle.voucher_type,
               gle.voucher_no,
               SUM({cost}) AS cost,
               SUM({paid}) AS paid,
               GROUP_CONCAT(DISTINCT NULLIF(gle.party, '')
                   ORDER BY gle.party SEPARATOR ' · ') AS parties,
               MAX(gle.remarks) AS remarks,
               MAX(CASE WHEN gle.voucher_type = 'Payment Entry'
                        THEN pe.custom_source_voucher_doctype ELSE
                    CASE WHEN gle.voucher_type = 'Journal Entry'
                        THEN je.custom_source_voucher_doctype ELSE NULL END
               END) AS source_doctype,
               MAX(CASE WHEN gle.voucher_type = 'Payment Entry'
                        THEN pe.custom_source_voucher ELSE
                    CASE WHEN gle.voucher_type = 'Journal Entry'
                        THEN je.custom_source_voucher ELSE NULL END
               END) AS source_voucher
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        LEFT JOIN `tabPayment Entry` pe
               ON pe.name = gle.voucher_no AND gle.voucher_type = 'Payment Entry'
        LEFT JOIN `tabJournal Entry` je
               ON je.name = gle.voucher_no AND gle.voucher_type = 'Journal Entry'
        WHERE gle.company = %(company)s AND gle.project = %(project)s
          AND gle.is_cancelled = 0
          AND gle.posting_date <= %(to_date)s
          {floor}
        GROUP BY gle.posting_date, gle.voucher_type, gle.voucher_no
        ORDER BY gle.posting_date DESC, gle.voucher_no DESC
        """.format(cost=_COST_SQL, paid=_PAID_SQL,
                   floor="AND gle.posting_date >= %(from_date)s" if from_date else ""),
        {"company": company, "project": project,
         "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    out = []
    for r in rows:
        doctype = r["source_doctype"] or r["voucher_type"]
        name = r["source_voucher"] or r["voucher_no"]
        out.append({
            "posting_date": str(r["posting_date"]),
            "doctype": doctype,
            "name": name,
            "kind": _KIND.get(doctype, doctype),
            "posted_as": r["voucher_no"] if r["source_voucher"] else None,
            "party": r["parties"] or None,
            "remark": (r["remarks"] or "").strip() or None,
            "cost": flt(r["cost"]),
            "paid": flt(r["paid"]),
        })
    return out


def _chain(company, project, commitment, vouchers, as_at=None):
    """Count and value at each stage of the spend chain, in order.

    The first two stages are document-derived — orders post no ledger
    entries. The last two are read straight off the ledger rows above, so
    Invoiced and Paid here are the same numbers as the KPI row and the
    against-estimate bar rather than a second opinion assembled from
    Purchase Invoice totals.
    """
    def counted(rows, key):
        hit = [v for v in rows if abs(v[key]) > 0.005]
        mix = {}
        for v in hit:
            mix[v["kind"]] = mix.get(v["kind"], 0) + 1
        detail = " · ".join(
            "{0} {1}{2}".format(n, k.lower(), "" if n == 1 else "s")
            for k, n in sorted(mix.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        return len(hit), flt(sum(v[key] for v in hit)), detail

    inv_count, inv_value, inv_detail = counted(vouchers, "cost")
    paid_count, paid_value, paid_detail = counted(vouchers, "paid")

    return [
        {"stage": _("Work Orders"), "count": commitment["wo"]["count"],
         "value": flt(commitment["wo"]["value"]), "source": "document",
         "detail": _work_order_suppliers(company, project, as_at=as_at)},
        {"stage": _("Purchase Orders"), "count": commitment["po"]["count"],
         "value": flt(commitment["po"]["value"]), "source": "document",
         "detail": ""},
        {"stage": _("Invoiced"), "count": inv_count, "value": inv_value,
         "source": "ledger", "detail": inv_detail},
        {"stage": _("Paid"), "count": paid_count, "value": paid_value,
         "source": "ledger", "detail": paid_detail},
    ]


def _work_order_suppliers(company, project, limit=2, as_at=None):
    """Who the work orders are with — a caption, not a figure."""
    if not frappe.db.exists("DocType", "Work Order Contract"):
        return ""
    names = [r[0] for r in frappe.db.sql(
        """
        SELECT DISTINCT COALESCE(NULLIF(supplier_name, ''), supplier)
        FROM `tabWork Order Contract`
        WHERE docstatus = 1 AND company = %(company)s AND project = %(project)s
          {cutoff}
        ORDER BY 1
        """.format(cutoff="AND wo_date <= %(as_at)s" if as_at else ""),
        {"company": company, "project": project, "as_at": as_at}) if r[0]]
    if not names:
        return ""
    if len(names) <= limit:
        return ", ".join(names)
    return "{0} +{1} more".format(", ".join(names[:limit]), len(names) - limit)


# =====================================================================
# Linking an invoice to its work order, from the dashboard
# =====================================================================
#
# ``Purchase Invoice.work_order_contract`` carries ``allow_on_submit = 0`` and
# every invoice worth linking is submitted, so ``doc.save()`` is not merely
# inconvenient — Frappe rejects it outright with UpdateAfterSubmitError. The
# only route is ``db.set_value``, which writes the column and runs nothing
# else.
#
# That is safe here, and the reason it is safe is specific rather than
# general. The field's whole behaviour in dux_civil_works is a
# ``before_validate`` hook that fills a BLANK header project from the work
# order and cascades it to item rows; with ``allow_on_submit = 0`` that hook
# can never fire on a submitted document at all. Nothing on the Work Order
# Contract side is maintained — it has no billed-to-date field, no status,
# no invoice table — so there is no aggregate left stale by writing the
# column directly. The RA-bill machinery is keyed off the ITEM-level
# ``wo_ra_bill``, never off this header link.
#
# Writing the column directly does skip the app's own company check, so it is
# re-implemented below, along with the supplier check the app only enforces
# in client script and therefore does not enforce at all.
#
# Two consequences the caller is told about rather than protected from:
# linking makes the Work Order Contract un-cancellable (Frappe's own link
# check), and db.set_value writes no Version row, so a timeline Comment is
# added instead to leave an audit trail.


def _require_wo_link():
    """Refuse the link actions on a site whose Purchase Invoice has no
    work-order column, rather than letting a raw SQL error surface."""
    if not _has_wo_link():
        frappe.throw(
            _("This site's Purchase Invoice has no work-order link field. "
              "It ships with the Work Orders app — ask an administrator to "
              "update it before linking invoices to work orders."),
            frappe.ValidationError)


def _assert_can_link(invoice, work_order=None):
    """Everything that must hold before the column is written."""
    require_access()
    frappe.has_permission("Purchase Invoice", "write", doc=invoice, throw=True)

    cols = ["name", "company", "supplier", "project", "docstatus"]
    if _has_wo_link():
        cols.append("work_order_contract")
    pi = frappe.db.get_value("Purchase Invoice", invoice, cols, as_dict=True)
    if pi and "work_order_contract" not in pi:
        pi.work_order_contract = None
    if not pi:
        frappe.throw(_("Purchase Invoice {0} not found").format(invoice))
    if pi.docstatus == 2:
        frappe.throw(_("{0} is cancelled.").format(invoice))
    if not pi.project:
        # The link fills a blank project on a later save, and project is a
        # GL-repost trigger on Purchase Invoice. Refuse rather than leave a
        # document that reposts the ledger the next time someone edits it.
        frappe.throw(_("{0} has no project, so it cannot be linked from here.")
                     .format(invoice))
    _resolve_companies([pi.company]) or frappe.throw(
        _("You do not have access to {0}.").format(pi.company),
        frappe.PermissionError)

    if work_order is None:
        return pi, None

    wo = frappe.db.get_value(
        "Work Order Contract", work_order,
        ["name", "company", "supplier", "project", "docstatus",
         "total_amount", "work_title"], as_dict=True)
    if not wo:
        frappe.throw(_("Work Order {0} not found").format(work_order))
    if wo.docstatus != 1:
        frappe.throw(_("Work Order {0} is not submitted.").format(work_order))
    # The app's own guard, re-implemented because db.set_value skips validate.
    if wo.company != pi.company:
        frappe.throw(_("{0} belongs to {1}, but the invoice is on {2}.")
                     .format(work_order, wo.company, pi.company))
    # The app enforces this only in client script, so it is not enforced at
    # all against a direct call.
    if wo.supplier != pi.supplier:
        frappe.throw(_("{0} is with {1}, but the invoice is from {2}.")
                     .format(work_order, wo.supplier, pi.supplier))
    if wo.project != pi.project:
        frappe.throw(_("{0} is on project {1}, but the invoice is on {2}.")
                     .format(work_order, wo.project, pi.project))
    return pi, wo


@frappe.whitelist()
def get_link_options(invoice):
    """The work orders this invoice could belong to, with what each would become.

    Scoped to the invoice's own supplier and project — those are the two
    constraints the link must satisfy, so offering anything else would only
    produce an error on submit. Each option carries what it is already billed
    and what this invoice would take it to, because "which contract" is a
    judgement someone makes on the numbers.
    """
    pi, _wo = _assert_can_link(invoice)
    _require_wo_link()

    value = flt(frappe.db.sql(
        """
        SELECT SUM(base_net_amount) FROM `tabPurchase Invoice Item`
        WHERE parent = %s
        """, invoice)[0][0])

    orders = frappe.db.sql(
        """
        SELECT name, work_title, wo_date, total_amount
        FROM `tabWork Order Contract`
        WHERE docstatus = 1 AND company = %(company)s
          AND supplier = %(supplier)s AND project = %(project)s
        ORDER BY total_amount DESC
        """,
        {"company": pi.company, "supplier": pi.supplier, "project": pi.project},
        as_dict=True,
    )
    if not orders:
        return {"invoice": invoice, "supplier": pi.supplier, "value": value,
                "linked_to": pi.work_order_contract, "options": []}

    billed = dict(frappe.db.sql(
        """
        SELECT pi.work_order_contract, SUM(pii.base_net_amount)
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.docstatus = 1 AND pi.work_order_contract IN %(orders)s
          AND pi.name <> %(invoice)s
        GROUP BY pi.work_order_contract
        """,
        {"orders": tuple(o["name"] for o in orders), "invoice": invoice}) or [])

    options = []
    for o in orders:
        already = flt(billed.get(o["name"]))
        ordered = flt(o["total_amount"])
        after = already + value
        options.append({
            "name": o["name"],
            "title": o["work_title"],
            "wo_date": str(o["wo_date"]) if o["wo_date"] else None,
            "ordered": ordered,
            "billed": already,
            "left": flt(ordered - already),
            "after": after,
            "pct_after": flt(after / ordered * 100) if ordered else None,
            "overbills": bool(ordered and after > ordered + 0.005),
            "current": o["name"] == pi.work_order_contract,
        })
    return {"invoice": invoice, "supplier": pi.supplier, "value": value,
            "linked_to": pi.work_order_contract, "options": options}


@frappe.whitelist()
def link_invoice_to_work_order(invoice, work_order):
    """Point a submitted invoice at its work order. See the note above."""
    pi, wo = _assert_can_link(invoice, work_order)
    _require_wo_link()
    previous = pi.work_order_contract
    if previous == work_order:
        return {"invoice": invoice, "work_order": work_order, "changed": False}

    frappe.db.set_value("Purchase Invoice", invoice, "work_order_contract",
                        work_order, update_modified=False)
    _note(invoice, _("Linked to work order {0}{1}.").format(
        work_order, _(" (was {0})").format(previous) if previous else ""))
    return {"invoice": invoice, "work_order": work_order,
            "previous": previous, "changed": True}


@frappe.whitelist()
def unlink_invoice_from_work_order(invoice):
    """Undo a link. Without this the dashboard action is one-way, and it also
    releases the work order, which cannot be cancelled while an invoice
    points at it."""
    pi, _wo = _assert_can_link(invoice)
    _require_wo_link()
    if not pi.work_order_contract:
        return {"invoice": invoice, "changed": False}

    frappe.db.set_value("Purchase Invoice", invoice, "work_order_contract",
                        None, update_modified=False)
    _note(invoice, _("Unlinked from work order {0}.").format(pi.work_order_contract))
    return {"invoice": invoice, "previous": pi.work_order_contract, "changed": True}


def _note(invoice, text):
    """db.set_value writes no Version row, so leave the trail by hand."""
    try:
        frappe.get_doc({
            "doctype": "Comment",
            "comment_type": "Info",
            "reference_doctype": "Purchase Invoice",
            "reference_name": invoice,
            "content": text,
        }).insert(ignore_permissions=True)
    except Exception:
        frappe.log_error(frappe.get_traceback(),
                         "project_dashboard: could not add link comment")


# =====================================================================
# Billing against each work order
# =====================================================================
#
# The Raisoni process is Work Order -> Purchase Invoice directly: no RA Bill
# sits between them, so ``Purchase Invoice.work_order_contract`` is the whole
# chain and this reads straight off it.
#
# Ordered and billed are compared on the SAME basis — both pre-tax.
# ``Work Order Contract.total_amount`` sums line amounts before tax (that app
# carries the taxed figure separately in ``total_amount_with_tax``), so
# billing is summed on ``base_net_amount`` rather than the invoice grand
# total. Comparing a taxed bill against an untaxed order would show every
# work order over-billed by its GST.
#
# There is deliberately no "paid" column. A payment settles a supplier's
# payable, not a particular contract — nothing in the ledger attributes cash
# to one work order, and inventing a split would be a guess. Who has been
# paid what is the party table's job.


def _has_wo_link():
    """Whether Purchase Invoice actually carries the work-order link column.

    dux_civil_works ships it as a Custom Field, so a site can have the Work
    Order Contract doctype and not the column — the doctype and the field
    arrived in different releases of that app. Checking the doctype alone
    lets a bare SQL error reach the user.
    """
    return bool(frappe.db.has_column("Purchase Invoice", "work_order_contract"))


def _work_order_billing(company, project, as_at=None):
    """Ordered against billed, per work order, plus what is not linked.

    The unlinked buckets are the point of the card as much as the rows are:
    an invoice on this project that names no work order is either material
    bought on a purchase order — normal — or an unattributed bill someone
    still has to place, and the two should not look alike.
    """
    if not frappe.db.exists("DocType", "Work Order Contract"):
        return None

    linked = _has_wo_link()
    cutoff = "AND wo.wo_date <= %(as_at)s" if as_at else ""
    orders = frappe.db.sql(
        """
        SELECT wo.name, wo.supplier,
               COALESCE(NULLIF(wo.supplier_name, ''), wo.supplier) AS supplier_name,
               wo.wo_date, wo.work_title, wo.total_amount AS ordered
        FROM `tabWork Order Contract` wo
        WHERE wo.docstatus = 1 AND wo.company = %(company)s
          AND wo.project = %(project)s
          {cutoff}
        ORDER BY wo.total_amount DESC
        """.format(cutoff=cutoff),
        {"company": company, "project": project, "as_at": as_at},
        as_dict=True,
    )

    # Every submitted purchase invoice on this project, one row per invoice,
    # carrying whichever work order it names and whether its lines came off a
    # purchase order.
    invoices = frappe.db.sql(
        """
        SELECT pi.name,
               pi.supplier,
               pi.posting_date,
               {wo_col}                             AS wo,
               SUM(pii.base_net_amount)             AS value,
               MAX(CASE WHEN COALESCE(pii.purchase_order, '') <> ''
                        THEN 1 ELSE 0 END)          AS from_po
        FROM `tabPurchase Invoice Item` pii
        INNER JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
        WHERE pi.docstatus = 1 AND pi.company = %(company)s
          AND COALESCE(NULLIF(pii.project, ''), pi.project) = %(project)s
          AND pi.posting_date <= %(to_date)s
        GROUP BY pi.name, pi.supplier, pi.posting_date, {wo_col}
        ORDER BY pi.posting_date DESC, pi.name DESC
        """.format(wo_col="pi.work_order_contract" if linked else "NULL"),
        {"company": company, "project": project, "to_date": as_at or "2999-12-31"},
        as_dict=True,
    )

    billed = {}
    counts = {}
    # The invoices behind each row, so a linked one stays reachable. Without
    # this the link action is one-way: once an invoice is attributed it
    # leaves the unlinked block and there is nowhere left to undo it from.
    attached = {}
    for inv in invoices:
        if inv["wo"]:
            billed[inv["wo"]] = flt(billed.get(inv["wo"])) + flt(inv["value"])
            counts[inv["wo"]] = counts.get(inv["wo"], 0) + 1
            attached.setdefault(inv["wo"], []).append({
                "name": inv["name"],
                "posting_date": str(inv["posting_date"]),
                "value": flt(inv["value"]),
            })

    rows = []
    for o in orders:
        b = flt(billed.get(o["name"]))
        ordered = flt(o["ordered"])
        rows.append({
            "name": o["name"],
            "supplier": o["supplier_name"] or o["supplier"],
            "wo_date": str(o["wo_date"]) if o["wo_date"] else None,
            "title": o["work_title"],
            "ordered": ordered,
            "billed": b,
            "balance": flt(ordered - b),
            "invoices": counts.get(o["name"], 0),
            "invoice_list": attached.get(o["name"], []),
            "pct": flt(b / ordered * 100) if ordered else None,
        })

    def bucket(rows_):
        """Grouped by supplier, because that is the question it answers.

        A contractor's Billed in the party table counts every bill they
        raised; the work-order rows count only the bills that name a work
        order. The difference is exactly what lands here, so naming the
        supplier is what lets a reader tie the two cards together instead
        of doing the subtraction themselves.
        """
        by_supplier = {}
        for r in rows_:
            b = by_supplier.setdefault(r["supplier"], {
                "supplier": r["supplier"], "value": 0.0, "invoices": [],
            })
            b["value"] += flt(r["value"])
            b["invoices"].append({
                "name": r["name"],
                "posting_date": str(r["posting_date"]),
                "value": flt(r["value"]),
            })
        suppliers = sorted(by_supplier.values(), key=lambda x: -x["value"])
        return {"value": flt(sum(flt(r["value"]) for r in rows_)),
                "count": len(rows_),
                "suppliers": suppliers}

    on_po = bucket([i for i in invoices if not i["wo"] and i["from_po"]])
    loose = bucket([i for i in invoices if not i["wo"] and not i["from_po"]])

    return {
        "rows": rows,
        "totals": {
            "ordered": flt(sum(r["ordered"] for r in rows)),
            "billed": flt(sum(r["billed"] for r in rows)),
            "balance": flt(sum(r["balance"] for r in rows)),
        },
        "on_purchase_orders": on_po,
        "unattributed": loose,
        "invoice_total": flt(sum(flt(i["value"]) for i in invoices)),
    }


# =====================================================================
# Who the money is with
# =====================================================================
#
# The party dimension cannot be read off the cost side of the ledger. A
# Purchase Invoice debits CWIP or an expense head with NO party and credits
# the payable WITH one, so every rupee of "cost" on this site sits on rows
# whose party is blank — measured on PROJ-0007: 85,17,106 of cost, none of
# it party-tagged.
#
# So party-wise money is read off the PAYABLE account, the same side Paid
# already comes from:
#
#   billed  = SUM(credit) on Payable   — bills raised against the project
#   paid    = SUM(debit)  on Payable   — settlements
#   owed    = billed - paid, floored at zero
#   advance = paid - billed, floored at zero
#
# ``owed`` and ``advance`` are kept apart rather than netted into one signed
# balance: a project can genuinely be both owed money on one contractor and
# ahead on another, and one signed column hides whichever is smaller.
#
# These figures are on a different basis from the Invoiced / Outstanding
# pair above them, and will not net to the same number. The bridge is
# ``cost_without_party`` — cost booked to the project whose payable leg was
# never tagged. On the seeded rent journals the debit row carries the
# project and the credit row to Creditors does not, which is exactly how a
# contractor ends up showing as paid with nothing billed.


def _party_commitments(companies, project_names, as_at=None):
    """{(project, party): {"wo": {...}, "po": {...}}} — what is on order.

    Document-derived, like ``_commitments``, which this is the party-wise
    cut of. Kept separate rather than folded in, because the portfolio
    totals never need it and it is two more queries.
    """
    out = {}
    if not project_names:
        return out

    po_cutoff = "AND po.transaction_date <= %(as_at)s" if as_at else ""
    wo_cutoff = "AND wo_date <= %(as_at)s" if as_at else ""

    def bucket(project, party):
        return out.setdefault((project, party), {
            "wo": {"count": 0, "value": 0.0},
            "po": {"count": 0, "value": 0.0},
        })

    for r in frappe.db.sql(
        """
        SELECT COALESCE(NULLIF(poi.project, ''), po.project) AS project,
               po.supplier                                   AS party,
               SUM(poi.base_amount)                          AS value,
               COUNT(DISTINCT po.name)                       AS orders
        FROM `tabPurchase Order Item` poi
        INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
        WHERE po.docstatus = 1
          AND po.status NOT IN ('Closed', 'Cancelled')
          AND po.company IN %(companies)s
          AND COALESCE(NULLIF(poi.project, ''), po.project) IN %(projects)s
          {po_cutoff}
        GROUP BY project, po.supplier
        """.format(po_cutoff=po_cutoff),
        {"companies": tuple(companies), "projects": tuple(project_names),
         "as_at": as_at},
        as_dict=True,
    ):
        if r["project"] and r["party"]:
            bucket(r["project"], r["party"])["po"] = {
                "count": int(r["orders"] or 0), "value": flt(r["value"])}

    if frappe.db.exists("DocType", "Work Order Contract"):
        for r in frappe.db.sql(
            """
            SELECT project, supplier AS party,
                   SUM(total_amount) AS value, COUNT(*) AS contracts
            FROM `tabWork Order Contract`
            WHERE docstatus = 1
              AND company IN %(companies)s
              AND project IN %(projects)s
              {wo_cutoff}
            GROUP BY project, supplier
            """.format(wo_cutoff=wo_cutoff),
            {"companies": tuple(companies), "projects": tuple(project_names),
             "as_at": as_at},
            as_dict=True,
        ):
            if r["project"] and r["party"]:
                bucket(r["project"], r["party"])["wo"] = {
                    "count": int(r["contracts"] or 0), "value": flt(r["value"])}

    return out


def _payable_by_party(company, from_date, to_date, project=None):
    """{(project, party): {...}} off the payable account, one query.

    ``account`` comes back with it because the Party Ledger deep-link
    refuses to run without one.
    """
    where = "AND gle.project = %(project)s" if project \
        else "AND COALESCE(gle.project, '') <> ''"
    # ``from_date`` may be None: the party position is project-to-date, to
    # match the Paid figure it sits under.
    if from_date:
        where += " AND gle.posting_date >= %(from_date)s"

    rows = frappe.db.sql(
        """
        SELECT gle.project        AS project,
               gle.party          AS party,
               gle.party_type     AS party_type,
               MAX(gle.account)   AS account,
               SUM(gle.credit)    AS billed,
               SUM(gle.debit)     AS paid
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s
          AND gle.is_cancelled = 0
          AND COALESCE(acc.account_type, '') = 'Payable'
          AND COALESCE(gle.party, '') <> ''
          AND gle.posting_date <= %(to_date)s
          {where}
        GROUP BY gle.project, gle.party, gle.party_type
        """.format(where=where),
        {"company": company, "project": project,
         "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )
    return {(r["project"], r["party"]): r for r in rows}


def _party_rows(projects, commitments, payable):
    """Merge the ordered side and the ledger side into one row per party.

    ``projects`` maps project -> company, so the same helper serves one
    project on the drill-down and a whole filtered selection on the
    portfolio. Each row keeps the companies it drew from: the Party Ledger
    deep-link needs exactly one, and a party working for two institutes
    cannot be opened unambiguously.
    """
    agg = {}

    def row(party, company, party_type=None, account=None):
        r = agg.setdefault(party, {
            "party": party, "party_type": party_type or "Supplier",
            "companies": set(), "account": None,
            "wo": 0.0, "po": 0.0, "ordered": 0.0, "billed": 0.0, "paid": 0.0,
        })
        if company:
            r["companies"].add(company)
        if party_type:
            r["party_type"] = party_type
        if account and not r["account"]:
            r["account"] = account
        return r

    for (project, party), c in commitments.items():
        if project not in projects:
            continue
        r = row(party, projects[project])
        r["wo"] += flt(c["wo"]["value"])
        r["po"] += flt(c["po"]["value"])

    for (project, party), g in payable.items():
        if project not in projects:
            continue
        r = row(party, projects[project], g.get("party_type"), g.get("account"))
        r["billed"] += flt(g["billed"])
        r["paid"] += flt(g["paid"])

    # A party that only ever appeared on a work order has no ledger row, so
    # no account came back with it — and the Party Ledger refuses to open
    # without one. Resolve those from the party's own default, per company.
    wanted = {}
    for r in agg.values():
        if not r["account"] and len(r["companies"]) == 1:
            wanted.setdefault(next(iter(r["companies"])), []).append(r["party"])
    resolved = {}
    for co, parties in wanted.items():
        for party, acc in _default_payable_accounts(co, parties).items():
            resolved[(co, party)] = acc

    out = []
    for r in agg.values():
        company = next(iter(r["companies"])) if len(r["companies"]) == 1 else None
        if not r["account"] and company:
            r["account"] = resolved.get((company, r["party"]))
        r["company"] = company
        r.pop("companies", None)
        r["ordered"] = flt(r["wo"] + r["po"])
        r["owed"] = flt(max(0.0, r["billed"] - r["paid"]))
        r["advance"] = flt(max(0.0, r["paid"] - r["billed"]))
        out.append(r)

    # Largest relationship first — ordered value if there is one, else what
    # has actually moved through the ledger.
    out.sort(key=lambda r: (-(r["ordered"] or r["billed"] or r["paid"]),
                            r["party"]))
    return out


def _default_payable_accounts(company, parties):
    """Each party's default payable account, for the ledger deep-link."""
    out = {}
    try:
        from erpnext.accounts.party import get_party_account
    except ImportError:
        return out
    for party in parties[:50]:
        try:
            out[party] = get_party_account("Supplier", party, company)
        except Exception:
            continue
    return out


def _party_totals(rows, invoiced):
    billed = flt(sum(r["billed"] for r in rows))
    return {
        "ordered": flt(sum(r["ordered"] for r in rows)),
        "billed": billed,
        "paid": flt(sum(r["paid"] for r in rows)),
        "owed": flt(sum(r["owed"] for r in rows)),
        "advance": flt(sum(r["advance"] for r in rows)),
        # The bridge back to Invoiced: cost booked to the project whose
        # payable leg never carried the project, so it reached no party.
        "cost_without_party": flt(invoiced - billed),
    }
