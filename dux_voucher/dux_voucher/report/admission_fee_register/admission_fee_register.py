"""Admission Fee Register — flat list of submitted Student Fee Receipts
with KPI summary cards.

Designed for the institution's accounts team to answer questions like
"how many admissions this month?", "what's the total fees collected
for FY 2026-27?", and "what's MCA's admission count year-to-date?".

Only submitted receipts are included — drafts are in-progress and
shouldn't be counted as collected revenue.

Filters: Company (required), From Date (required), To Date (required),
Course (optional), Admission Year (optional), Mode of Payment (optional).

Returns: (columns, rows, message, chart, summary).
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


def execute(filters=None):
    filters = frappe._dict(filters or {})
    _validate_filters(filters)

    columns = _get_columns()
    rows = _get_rows(filters)
    summary = _get_summary(rows)
    chart = _get_chart(rows)
    return columns, rows, None, chart, summary


# ── Filters ─────────────────────────────────────────────────────────

def _validate_filters(f):
    if not f.company:
        frappe.throw(_("Company is required."))
    if not f.from_date or not f.to_date:
        frappe.throw(_("From Date and To Date are both required."))
    if getdate(f.from_date) > getdate(f.to_date):
        frappe.throw(_("From Date cannot be after To Date."))


# ── Columns ─────────────────────────────────────────────────────────

def _get_columns():
    return [
        {"label": _("Posting Date"),    "fieldname": "posting_date",
         "fieldtype": "Date",           "width": 110},
        {"label": _("Receipt"),         "fieldname": "name",
         "fieldtype": "Link",           "options": "Student Fee Receipt",
         "width": 140},
        {"label": _("Student"),         "fieldname": "student",
         "fieldtype": "Link",           "options": "Student",
         "width": 110},
        {"label": _("Student Name"),    "fieldname": "student_name",
         "fieldtype": "Data",           "width": 180},
        {"label": _("Father's Name"),   "fieldname": "father_name",
         "fieldtype": "Data",           "width": 150},
        {"label": _("Course"),          "fieldname": "course",
         "fieldtype": "Link",           "options": "Course",
         "width": 100},
        {"label": _("Admission Year"),  "fieldname": "admission_year",
         "fieldtype": "Data",           "width": 120},
        {"label": _("Total Amount"),    "fieldname": "total_amount",
         "fieldtype": "Currency",       "width": 130},
        {"label": _("Mode of Payment"), "fieldname": "mode_of_payment",
         "fieldtype": "Link",           "options": "Mode of Payment",
         "width": 140},
        {"label": _("Received In"),     "fieldname": "received_in_account",
         "fieldtype": "Link",           "options": "Account",
         "width": 200},
        {"label": _("Reference No"),    "fieldname": "reference_no",
         "fieldtype": "Data",           "width": 140},
        {"label": _("Backend JE"),      "fieldname": "backend_je",
         "fieldtype": "Link",           "options": "Journal Entry",
         "width": 140},
    ]


# ── Rows ────────────────────────────────────────────────────────────

def _get_rows(f):
    """Submitted receipts only. Filters compose with AND."""
    conditions = ["docstatus = 1"]
    params = {}

    conditions.append("company = %(company)s")
    params["company"] = f.company

    conditions.append("posting_date BETWEEN %(from_date)s AND %(to_date)s")
    params["from_date"] = f.from_date
    params["to_date"]   = f.to_date

    if f.course:
        conditions.append("course = %(course)s")
        params["course"] = f.course

    if f.admission_year:
        conditions.append("admission_year = %(admission_year)s")
        params["admission_year"] = f.admission_year

    if f.mode_of_payment:
        conditions.append("mode_of_payment = %(mode_of_payment)s")
        params["mode_of_payment"] = f.mode_of_payment

    sql = f"""
        SELECT
            posting_date, name, student, student_name, father_name,
            course, admission_year, total_amount, mode_of_payment,
            received_in_account, reference_no, backend_je
        FROM `tabStudent Fee Receipt`
        WHERE {' AND '.join(conditions)}
        ORDER BY posting_date DESC, creation DESC
    """
    return frappe.db.sql(sql, params, as_dict=True)


# ── Summary cards (KPI strip at the top of the report) ─────────────

def _get_summary(rows):
    if not rows:
        return [
            _kpi(_("Receipts"),         0,    "blue",   "fa fa-list"),
            _kpi(_("Total Collected"),  0.0,  "green",  "fa fa-rupee",
                 currency=True),
            _kpi(_("Distinct Students"),0,    "purple", "fa fa-users"),
        ]
    total = sum(flt(r.total_amount) for r in rows)
    distinct_students = len({r.student for r in rows if r.student})
    return [
        _kpi(_("Receipts"),         len(rows),        "blue",   "fa fa-list"),
        _kpi(_("Total Collected"),  total,            "green",  "fa fa-rupee",
             currency=True),
        _kpi(_("Distinct Students"),distinct_students,"purple", "fa fa-users"),
    ]


def _kpi(label, value, color, icon, currency=False):
    card = {
        "label":     label,
        "value":     value,
        "indicator": color,
        "icon":      icon,
    }
    if currency:
        card["datatype"] = "Currency"
    else:
        card["datatype"] = "Int"
    return card


# ── Chart (count + amount per Admission Year) ───────────────────────

def _get_chart(rows):
    """A small bar chart of receipt count per Admission Year — useful
    visual at a glance for year-over-year comparison.

    Falls back to no chart if there's only one year in the result set
    (chart would be a single bar, not informative).
    """
    if not rows:
        return None

    by_year = {}
    for r in rows:
        y = r.admission_year or _("(unset)")
        by_year[y] = by_year.get(y, 0) + 1

    if len(by_year) < 2:
        return None

    sorted_years = sorted(by_year.keys())
    return {
        "data": {
            "labels":   sorted_years,
            "datasets": [
                {"name": _("Receipts"), "values": [by_year[y] for y in sorted_years]}
            ],
        },
        "type":         "bar",
        "colors":       ["#0F6E56"],
        "barOptions":   {"stacked": False},
    }
