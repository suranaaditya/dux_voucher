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


# GL rows with no project are bucketed under this sentinel so one grouped
# query can serve both the per-project figures and the unattributed total.
NO_PROJECT = "\x00none"

# Accounts that represent the project's own cost. Bank/cash is the payment
# side and party accounts are settlement — neither is a cost.
_COST_SQL = """
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
    """
    companies = _resolve_companies(companies)
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
    unattributed = 0.0
    unattributed_rows = 0

    for company in scan:
        rows = _gl_for_company(company, from_date, to_date)
        used_accounts = {
            r["account"] for r in rows if r["project"] != NO_PROJECT
        }
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
                "cost": 0.0, "paid": 0.0, "entries": 0, "last_activity": None
            })
            agg["cost"] += flt(r["cost"])
            agg["paid"] += flt(r["paid"])
            agg["entries"] += int(r["entries"] or 0)
            if r["last_activity"] and (
                not agg["last_activity"] or r["last_activity"] > agg["last_activity"]
            ):
                agg["last_activity"] = r["last_activity"]

    committed = _committed_from_po(companies, projects.keys())
    rows = _assemble(projects, gl, committed)

    return {
        "period": {"from_date": str(from_date), "to_date": str(to_date)},
        "companies": scan,
        "companies_permitted": len(companies),
        "kpi": _kpis(rows, unattributed, unattributed_rows),
        "projects": rows,
        "by_company": _by_company(rows),
        "attention": _attention(rows, unattributed, unattributed_rows),
        "generated_on": frappe.utils.now(),
    }


# =====================================================================
# Sources
# =====================================================================

def _gl_for_company(company, from_date, to_date):
    """One grouped query per company, keyed on (project, account).

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
               SUM({paid})                                  AS paid,
               COUNT(*)                                     AS entries,
               MAX(gle.posting_date)                        AS last_activity
        FROM `tabGL Entry` gle
        INNER JOIN `tabAccount` acc ON acc.name = gle.account
        WHERE gle.company = %(company)s
          AND gle.is_cancelled = 0
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY project, gle.account
        """.format(cost=_COST_SQL, paid=_PAID_SQL),
        {
            "company": company,
            "from_date": from_date,
            "to_date": to_date,
            "none": NO_PROJECT,
        },
        as_dict=True,
    )


def _committed_from_po(companies, project_names):
    """Purchase Orders tagged to a project.

    Document-derived, NOT from GL — a Purchase Order posts no ledger
    entries. Item-level project wins over the header, mirroring ERPNext's
    own dimension precedence. The PO tables are small enough that one
    query across companies is fine; the per-company loop exists for GL.
    """
    if not project_names:
        return {}

    rows = frappe.db.sql(
        """
        SELECT COALESCE(NULLIF(poi.project, ''), po.project) AS project,
               SUM(poi.base_amount)                          AS committed
        FROM `tabPurchase Order Item` poi
        INNER JOIN `tabPurchase Order` po ON po.name = poi.parent
        WHERE po.docstatus = 1
          AND po.status NOT IN ('Closed', 'Cancelled')
          AND po.company IN %(companies)s
          AND COALESCE(NULLIF(poi.project, ''), po.project) IN %(projects)s
        GROUP BY project
        """,
        {"companies": tuple(companies), "projects": tuple(project_names)},
        as_dict=True,
    )
    return {r["project"]: flt(r["committed"]) for r in rows if r["project"]}


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
        com = flt(committed.get(name))

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


def _kpis(rows, unattributed, unattributed_rows):
    committed = sum(r["committed"] for r in rows)
    invoiced = sum(r["invoiced"] for r in rows)
    paid = sum(r["paid"] for r in rows)
    return {
        "committed": flt(committed),
        "invoiced": flt(invoiced),
        "paid": flt(paid),
        "outstanding": flt(invoiced - paid),
        "uninvoiced": flt(committed - invoiced),
        "unattributed": flt(unattributed),
        "unattributed_entries": unattributed_rows,
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


def _attention(rows, unattributed, unattributed_rows):
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


def _resolve_companies(companies):
    """Company scoping is enforced here, not by narrowing the picker — a
    whitelisted endpoint is reachable directly."""
    from dux_voucher.dux_voucher.api.reports_api import get_permitted_companies

    if isinstance(companies, str):
        import json
        try:
            companies = json.loads(companies)
        except ValueError:
            companies = [companies] if companies else []
    companies = [c for c in (companies or []) if c]

    permitted = get_permitted_companies() or []
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
        "kpi": {"committed": 0, "invoiced": 0, "paid": 0, "outstanding": 0,
                "uninvoiced": 0, "unattributed": 0, "unattributed_entries": 0,
                "active_projects": 0, "total_projects": 0},
        "projects": [], "by_company": [], "attention": [],
        "generated_on": frappe.utils.now(),
    }


# =====================================================================
# Drill-down
# =====================================================================

@frappe.whitelist()
def get_project_detail(project, from_date=None, to_date=None):
    """Account-wise breakdown and recent documents for one project."""
    p = frappe.db.get_value(
        "Project", project,
        ["name", "project_name", "company", "status", "estimated_costing"],
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
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY gle.account
        HAVING amount <> 0
        ORDER BY amount DESC
        """.format(cost=_COST_SQL),
        {"company": p.company, "project": project,
         "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    recent = frappe.db.sql(
        """
        SELECT gle.posting_date, gle.voucher_type, gle.voucher_no,
               SUM(gle.debit) AS debit, SUM(gle.credit) AS credit
        FROM `tabGL Entry` gle
        WHERE gle.company = %(company)s AND gle.project = %(project)s
          AND gle.is_cancelled = 0
          AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
        GROUP BY gle.posting_date, gle.voucher_type, gle.voucher_no
        ORDER BY gle.posting_date DESC, gle.voucher_no DESC
        LIMIT 40
        """,
        {"company": p.company, "project": project,
         "from_date": from_date, "to_date": to_date},
        as_dict=True,
    )

    return {
        "project": p,
        "accounts": [{"account": r["account"], "amount": flt(r["amount"])}
                     for r in accounts],
        "recent": [{
            "posting_date": str(r["posting_date"]),
            "voucher_type": r["voucher_type"],
            "voucher_no": r["voucher_no"],
            "debit": flt(r["debit"]),
            "credit": flt(r["credit"]),
        } for r in recent],
    }
