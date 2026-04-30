"""Posting-date enforcement for the seven controlled DocTypes.

Wired from ``hooks.py`` as a ``validate`` doc_event. The site-wide
policy lives in the Single doctype ``Dux Backdating Settings``; this
module is the only consumer. No accounting logic — purely a date
guard.

Public entry point: :func:`enforce`.
Pure logic for unit tests: :func:`_check`.
"""

import frappe
from frappe import _
from frappe.utils import getdate


# Different ERPNext doctypes use different fieldnames for the posting
# date. Anything not listed falls back to ``posting_date``.
DATE_FIELDS = {
    "Purchase Order": "transaction_date",
}


# =====================================================================
# Public entry point
# =====================================================================

def enforce(doc, method=None):
    """``validate`` doc_event handler.

    Reads the Single settings (cached, sub-millisecond on warm cache),
    short-circuits on master-disabled or bypass-role match, then
    delegates to the pure :func:`_check` logic.
    """
    settings = frappe.get_cached_doc("Dux Backdating Settings")
    if not settings.enabled:
        return
    if _user_has_bypass_role(settings):
        return
    _check(doc, settings, today=getdate())


# =====================================================================
# Pure logic — no Frappe session state, fully unit-testable
# =====================================================================

def _check(doc, settings, today):
    """Apply the policy in ``settings`` to ``doc``, raising
    ``frappe.ValidationError`` on violation.

    Caller (i.e. :func:`enforce`) is expected to have already verified
    ``settings.enabled`` and the bypass-role check before reaching
    here — but we re-check ``enabled`` so the function can be called
    in isolation from tests that vary the flag.
    """
    if not settings.enabled:
        return

    if doc.get("amended_from") and not settings.enforce_for_amend:
        return

    rule = next(
        (r for r in (settings.rules or [])
         if r.target_doctype == doc.doctype),
        None,
    )
    if not rule:
        return

    date_field = DATE_FIELDS.get(doc.doctype, "posting_date")
    posting_raw = doc.get(date_field)
    if not posting_raw:
        # Let upstream "required" validation handle missing dates.
        return
    posting = getdate(posting_raw)

    if posting < today:
        days_back = (today - posting).days
        if not rule.allow_backdating:
            frappe.throw(
                _("Backdated entries are not allowed for {0}. "
                  "Today is {1}; the posting date must not be earlier.")
                .format(doc.doctype, today.isoformat())
            )
        if days_back > (rule.max_days_back or 0):
            frappe.throw(
                _("Backdated {0} entries are limited to {1} day(s) in "
                  "the past. The posting date {2} is {3} day(s) ago.")
                .format(
                    doc.doctype, rule.max_days_back or 0,
                    posting.isoformat(), days_back,
                )
            )

    elif posting > today:
        days_forward = (posting - today).days
        if not rule.allow_forward_dating:
            frappe.throw(
                _("Forward-dated entries are not allowed for {0}. "
                  "Today is {1}; the posting date must not be later.")
                .format(doc.doctype, today.isoformat())
            )
        if days_forward > (rule.max_days_forward or 0):
            frappe.throw(
                _("Forward-dated {0} entries are limited to {1} day(s) "
                  "in the future. The posting date {2} is {3} day(s) "
                  "ahead.").format(
                    doc.doctype, rule.max_days_forward or 0,
                    posting.isoformat(), days_forward,
                )
            )


# =====================================================================
# Bypass-role check — touches session state, kept separate from _check
# =====================================================================

def _user_has_bypass_role(settings):
    bypass = {b.role for b in (settings.bypass_roles or []) if b.role}
    if not bypass:
        return False
    user_roles = set(frappe.get_roles(frappe.session.user))
    return bool(bypass & user_roles)
