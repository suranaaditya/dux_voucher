"""Student Fee Refund Income — one place to see every admission-fee
refund, how much of each student's fee is still held in the Admission Fee
(Provisional) liability, and whether that retained amount has been booked
as income yet.

Per row the operator can book the student's remaining provisional balance
as income (the client `Book as income` button → student_fee.book_income).

"Remaining" is student-level, computed across ALL of the student's
submitted receipts/refunds (not just the filtered window):

    remaining = total paid − total refunded − income already booked

so it stays correct no matter how the date filter is set, and drops to
zero once booked.

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
    return columns, rows, None, None, summary


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
        {"label": _("Date"),          "fieldname": "posting_date",
         "fieldtype": "Date",         "width": 95},
        {"label": _("Refund"),        "fieldname": "refund",
         "fieldtype": "Link",         "options": "Student Fee Refund", "width": 130},
        {"label": _("Student"),       "fieldname": "student",
         "fieldtype": "Link",         "options": "Student", "width": 95},
        {"label": _("Student Name"),  "fieldname": "student_name",
         "fieldtype": "Data",         "width": 160},
        {"label": _("Course"),        "fieldname": "course",
         "fieldtype": "Link",         "options": "Course", "width": 85},
        {"label": _("Refund Amt"),    "fieldname": "refund_amount",
         "fieldtype": "Currency",     "width": 105},
        {"label": _("Paid"),          "fieldname": "paid",
         "fieldtype": "Currency",     "width": 105},
        {"label": _("Refunded"),      "fieldname": "refunded",
         "fieldtype": "Currency",     "width": 105},
        {"label": _("Remaining"),     "fieldname": "remaining",
         "fieldtype": "Currency",     "width": 110},
        {"label": _("Income Amt"),    "fieldname": "income_amount",
         "fieldtype": "Currency",     "width": 105},
        {"label": _("Income JE"),     "fieldname": "income_je",
         "fieldtype": "Link",         "options": "Journal Entry", "width": 125},
        {"label": _("Action"),        "fieldname": "action",
         "fieldtype": "Data",         "width": 140},
    ]


# ── Rows ────────────────────────────────────────────────────────────

def _get_rows(f):
    """Submitted refunds in the window, enriched with the student-level
    provisional balance and a per-row booking flag."""
    conditions = [
        "r.docstatus = 1",
        "r.company = %(company)s",
        "r.posting_date BETWEEN %(from_date)s AND %(to_date)s",
    ]
    params = {"company": f.company,
              "from_date": f.from_date, "to_date": f.to_date}
    if f.course:
        conditions.append("r.course = %(course)s")
        params["course"] = f.course

    refunds = frappe.db.sql(
        f"""SELECT r.name AS refund, r.posting_date, r.student, r.student_name,
                   r.course, r.total_amount, r.income_booked, r.income_amount,
                   r.income_je, r.income_booked_date
            FROM `tabStudent Fee Refund` r
            WHERE {' AND '.join(conditions)}
            ORDER BY r.posting_date DESC, r.creation DESC""",
        params, as_dict=True)

    students = list({r.student for r in refunds if r.student})
    bal_map = _bulk_balances(students, f.company)

    status = (f.status or "All")
    out = []
    for r in refunds:
        bal = bal_map.get(r.student, {})
        remaining = flt(bal.get("remaining"))
        booked = bool(r.income_booked)
        bookable = (not booked) and remaining > 0.005

        if status == "Pending" and not bookable:
            continue
        if status == "Booked" and not booked:
            continue

        out.append({
            "posting_date":  r.posting_date,
            "refund":        r.refund,
            "student":       r.student,
            "student_name":  r.student_name,
            "course":        r.course,
            "refund_amount": flt(r.total_amount),
            "paid":          flt(bal.get("paid")),
            "refunded":      flt(bal.get("refunded")),
            "remaining":     remaining,
            "income_amount": flt(r.income_amount) if booked else None,
            "income_je":     r.income_je,
            "income_booked": 1 if booked else 0,
            "bookable":      1 if bookable else 0,
            "action":        "",  # rendered client-side by the formatter
        })
    return out


def _bulk_balances(students, company):
    """One grouped query per leg → {student: {paid, refunded, income_booked,
    remaining}} for every student in the result, across all their docs."""
    if not students:
        return {}
    ph = ", ".join(["%s"] * len(students))
    args = [company] + students

    def _grouped_sum(table, col, extra=""):
        rows = frappe.db.sql(
            f"""SELECT student, COALESCE(SUM(`{col}`), 0)
                FROM `tab{table}`
                WHERE docstatus=1 AND company=%s {extra}
                  AND student IN ({ph})
                GROUP BY student""",
            args)
        return {s: flt(v) for s, v in rows}

    paid     = _grouped_sum("Student Fee Receipt", "total_amount")
    refunded = _grouped_sum("Student Fee Refund", "total_amount")
    booked   = _grouped_sum("Student Fee Refund", "income_amount",
                            extra="AND income_booked=1")

    out = {}
    for s in students:
        p  = flt(paid.get(s))
        rf = flt(refunded.get(s))
        bk = flt(booked.get(s))
        out[s] = {"paid": p, "refunded": rf, "income_booked": bk,
                  "remaining": flt(p - rf - bk)}
    return out


# ── Summary cards ───────────────────────────────────────────────────

def _get_summary(rows):
    refunds = len(rows)
    total_refunded = sum(flt(r["refund_amount"]) for r in rows)

    # Pending income is student-level — dedupe so a student with two
    # refund rows isn't counted twice.
    pending_by_student = {}
    for r in rows:
        if r["bookable"]:
            pending_by_student[r["student"]] = flt(r["remaining"])
    pending = sum(pending_by_student.values())

    booked = sum(flt(r["income_amount"] or 0) for r in rows if r["income_booked"])

    return [
        _kpi(_("Refunds"),        refunds,        "blue",   "fa fa-undo"),
        _kpi(_("Total Refunded"), total_refunded, "orange", "fa fa-rupee", currency=True),
        _kpi(_("Pending Income"), pending,        "red",    "fa fa-hourglass-half", currency=True),
        _kpi(_("Income Booked"),  booked,         "green",  "fa fa-check", currency=True),
    ]


def _kpi(label, value, color, icon, currency=False):
    return {
        "label":     label,
        "value":     value,
        "indicator": color,
        "icon":      icon,
        "datatype":  "Currency" if currency else "Int",
    }
