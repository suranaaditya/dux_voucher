"""Helpers for the Student admission-fee module.

Currently exposes one resolver — :func:`get_admission_fee_account` —
that maps a company to its 'Admission/Registration Fee (Provisional)'
liability account. The account is created manually by the user via
the standard ERPNext CoA UI (``Current Liabilities → Admission Fee
(Provisional) → Admission/Registration Fee (Provisional)``); this
resolver only locates it.

The "(Provisional)" qualifier reflects the fact that admission fees
are held against the future enrolment — refundable in some cases —
so the liability is provisional until confirmed.

Why not auto-create? Auto-creation in code is fragile — if the parent
group is named slightly differently across companies, or the user has
re-organised their CoA, an automatic path either fails opaquely or
ends up creating a stray ledger in the wrong place. Manual creation
once per company, with a clear error here when it's missing, is the
safer pattern.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate, nowdate, fmt_money

from dux_voucher.dux_voucher.api.utils import _submit_doc


ADMISSION_FEE_LEAF = "Admission/Registration Fee (Provisional)"
ADMISSION_FEE_GROUP = "Admission Fee (Provisional)"


def get_admission_fee_account(company):
    """Return the fully-qualified Account name for the Admission Fee
    liability under ``company``. Throws if the account is missing,
    with a clear message that points the user at the standard CoA
    setup step.
    """
    if not company:
        frappe.throw(_("Company is required to resolve the admission "
                        "fee account."))

    abbr = frappe.get_cached_value("Company", company, "abbr")
    if not abbr:
        frappe.throw(
            _("Company '{0}' has no abbreviation set. Set Company → "
              "Abbreviation before posting Student Fee Receipts.")
            .format(company)
        )

    name = f"{ADMISSION_FEE_LEAF} - {abbr}"
    if not frappe.db.exists("Account", name):
        frappe.throw(
            _("Account '{0}' does not exist. Create it under "
              "<strong>Current Liabilities → {1}</strong> "
              "in the Chart of Accounts before posting Student Fee "
              "Receipts for {2}.")
            .format(name, ADMISSION_FEE_GROUP, company)
        )
    return name


# =====================================================================
# Paid-summary helper (used by Student Fee Refund's form headline +
# soft-warn dialogs to compare the proposed refund against the
# student's total receipts to date)
# =====================================================================

def _total_paid_by_student(student, admission_year=None):
    """Sum of ``total_amount`` over the student's submitted Student
    Fee Receipts. Optionally constrained to a single admission year.

    Returns ``(paid_amount, receipt_count)``. Cancelled receipts are
    naturally excluded by the ``docstatus=1`` filter.

    Implemented with raw SQL because frappe.db.get_value rejects
    aggregate functions written as column strings (it requires the
    less-readable dict form for those). One round-trip query is fine
    for the form's headline.
    """
    if not student:
        return 0.0, 0

    params = {"student": student}
    extra = ""
    if admission_year:
        extra = " AND admission_year=%(year)s"
        params["year"] = admission_year

    row = frappe.db.sql(
        f"""SELECT COALESCE(SUM(total_amount), 0) AS paid,
                  COUNT(name)                    AS receipt_count
            FROM `tabStudent Fee Receipt`
            WHERE docstatus=1 AND student=%(student)s {extra}""",
        params, as_dict=True,
    )
    if not row:
        return 0.0, 0
    return flt(row[0].get("paid") or 0), int(row[0].get("receipt_count") or 0)


@frappe.whitelist()
def get_student_paid_summary(student, admission_year=None):
    """Whitelisted endpoint for the Student Fee Refund form to render
    its headline and to populate the cache that the validate-time
    soft-warn dialogs consult.

    Always returns a dict so the JS doesn't have to handle ``null``:
        {"paid": <float>, "receipt_count": <int>}
    """
    paid, count = _total_paid_by_student(student, admission_year)
    return {"paid": paid, "receipt_count": count}


# =====================================================================
# Retained-fee-as-income booking
# =====================================================================
#
# When an admission fee is only partly refunded, the amount the
# institution keeps stays as a Cr balance on the per-company
# 'Admission/Registration Fee (Provisional)' liability for that student.
# Booking it as income clears that balance:
#
#     Dr  Admission/Registration Fee (Provisional) - {abbr}   remaining
#     Cr  <Retained Fee Income Account from Student Fee Settings>  remaining
#
# The "remaining" is the student's net provisional balance —
#   total receipts (Cr) − total refunds (Dr) − income already booked —
# so re-booking is impossible once it hits zero.

RETAINED_INCOME_SETTINGS = "Student Fee Settings"
# Per-company convention account (mirrors the Admission Fee account's
# "<name> - {abbr}" naming). Created manually under Income → Indirect Income.
RETAINED_INCOME_LEAF = "Income From Admi Cancellation"
RETAINED_INCOME_GROUP = "Indirect Income"


def _student_provisional_balance(student, company):
    """Net amount still held in the Admission Fee (Provisional) liability
    for one student in one company.

        remaining = paid − refunded − income_already_booked

    Returns a dict (all floats) so callers — the refund form, the report,
    and the booking guard — share one definition of "remaining".
    """
    blank = {"paid": 0.0, "refunded": 0.0, "income_booked": 0.0, "remaining": 0.0}
    if not student or not company:
        return blank

    paid = frappe.db.sql(
        """SELECT COALESCE(SUM(total_amount), 0)
           FROM `tabStudent Fee Receipt`
           WHERE docstatus=1 AND student=%(s)s AND company=%(c)s""",
        {"s": student, "c": company})[0][0]

    refunded = frappe.db.sql(
        """SELECT COALESCE(SUM(total_amount), 0)
           FROM `tabStudent Fee Refund`
           WHERE docstatus=1 AND student=%(s)s AND company=%(c)s""",
        {"s": student, "c": company})[0][0]

    income_booked = frappe.db.sql(
        """SELECT COALESCE(SUM(income_amount), 0)
           FROM `tabStudent Fee Refund`
           WHERE docstatus=1 AND income_booked=1
             AND student=%(s)s AND company=%(c)s""",
        {"s": student, "c": company})[0][0]

    paid          = flt(paid)
    refunded      = flt(refunded)
    income_booked = flt(income_booked)
    return {
        "paid":          paid,
        "refunded":      refunded,
        "income_booked": income_booked,
        "remaining":     flt(paid - refunded - income_booked),
    }


@frappe.whitelist()
def get_student_remaining(student, company):
    """Whitelisted wrapper around :func:`_student_provisional_balance` for
    the refund form's booking dialog and the report's per-row action."""
    return _student_provisional_balance(student, company)


def get_retained_income_account(company):
    """Resolve the Retained Fee Income Account for ``company``.

    Resolution order:
      1. An explicit override set in Student Fee Settings (if any) — wins.
      2. Otherwise the per-company convention account
         ``'Income From Admi Cancellation - {abbr}'`` under
         Income → Indirect Income, mirroring the per-company naming of the
         Admission Fee account it is paired with.

    Either way the chosen account is validated (exists, is a ledger, and
    belongs to ``company`` — ERPNext won't accept a cross-company account
    in the Journal Entry).
    """
    if not company:
        frappe.throw(_("Company is required to resolve the income account."))

    abbr = frappe.get_cached_value("Company", company, "abbr")
    if not abbr:
        frappe.throw(
            _("Company '{0}' has no abbreviation set.").format(company))

    override = frappe.db.get_single_value(
        RETAINED_INCOME_SETTINGS, "retained_fee_income_account")
    if override:
        return _validate_income_account(
            override, company, source=_("Student Fee Settings"))

    name = f"{RETAINED_INCOME_LEAF} - {abbr}"
    if not frappe.db.exists("Account", name):
        frappe.throw(_(
            "Account '{0}' does not exist. Create it under <strong>Income "
            "&rarr; {1}</strong> in the Chart of Accounts, or set a "
            "<strong>Retained Fee Income Account</strong> in Student Fee "
            "Settings, before booking retained admission fees as income.")
            .format(name, RETAINED_INCOME_GROUP))
    return _validate_income_account(
        name, company, source=_("the Chart of Accounts"))


def _validate_income_account(acc, company, source):
    """Shared guard for both resolution paths — ledger account belonging
    to ``company``. ``source`` names where ``acc`` came from for the error
    messages."""
    if not frappe.db.exists("Account", acc):
        frappe.throw(_(
            "The income account '{0}' configured in {1} no longer exists.")
            .format(acc, source))

    meta = frappe.db.get_value(
        "Account", acc, ["company", "is_group"], as_dict=True) or {}
    if meta.get("is_group"):
        frappe.throw(_(
            "The income account '{0}' is a group account. Pick a ledger "
            "(leaf) account.").format(acc))
    if meta.get("company") and meta["company"] != company:
        frappe.throw(_(
            "The income account '{0}' belongs to {1}, but this refund is "
            "posted under {2}. Use an income account that belongs to {2}.")
            .format(acc, meta["company"], company))
    return acc


@frappe.whitelist()
def book_income(refund, posting_date=None):
    """Book a student's remaining provisional balance as income, anchored
    to the given submitted Student Fee Refund.

    Posts a 2-line JE (Dr Admission Fee Provisional, Cr Income account) for
    the FULL current remaining, then stamps the refund's income_* fields.
    Idempotent guard: a refund can only carry one income booking.

    The JE is intentionally NOT linked back via custom_source_voucher — see
    ``utils.on_journal_entry_cancel`` for how its cancellation is handled
    (it clears the booking rather than cancelling the refund).
    """
    doc = frappe.get_doc("Student Fee Refund", refund)
    doc.check_permission("write")

    if doc.docstatus != 1:
        frappe.throw(_("Income can only be booked against a submitted refund."))
    if doc.income_booked:
        frappe.throw(_(
            "Income is already booked for this refund (Journal Entry {0}).")
            .format(doc.income_je or ""))

    bal = _student_provisional_balance(doc.student, doc.company)
    remaining = flt(bal["remaining"])
    if remaining <= 0.005:
        frappe.throw(_(
            "There is no remaining provisional balance to book as income for "
            "this student (currently {0}).")
            .format(fmt_money(remaining, currency=_company_currency(doc.company))))

    income_account = get_retained_income_account(doc.company)
    admission_fee  = get_admission_fee_account(doc.company)
    pdate = getdate(posting_date) if posting_date else getdate(nowdate())

    je = frappe.new_doc("Journal Entry")
    je.voucher_type = "Journal Entry"
    je.company      = doc.company
    je.posting_date = pdate
    je.user_remark  = _("Retained admission fee booked as income — {0} ({1})").format(
        doc.student_name or doc.student, doc.admission_year)
    # No custom_source_voucher link — this JE is referenced the other way,
    # by Student Fee Refund.income_je, so its cancellation clears the
    # booking instead of cascading a cancel onto the refund.

    je.append("accounts", {
        "account":                    admission_fee,
        "debit_in_account_currency":  remaining,
        "credit_in_account_currency": 0,
        "user_remark":                _("Retained fee — {0}").format(
            doc.student_name or doc.student),
    })
    je.append("accounts", {
        "account":                    income_account,
        "debit_in_account_currency":  0,
        "credit_in_account_currency": remaining,
    })

    _submit_doc(je)

    doc.db_set("income_je", je.name)
    doc.db_set("income_amount", remaining)
    doc.db_set("income_booked", 1)
    doc.db_set("income_booked_date", pdate)

    return {"je": je.name, "amount": remaining, "income_account": income_account}


def _company_currency(company):
    return frappe.get_cached_value("Company", company, "default_currency") or "INR"
