"""Dux Backdating Settings — site-wide policy for posting-date controls.

The actual enforcement logic lives in
:mod:`dux_voucher.dux_voucher.api.backdating`; this controller only
keeps the rule table tidy. Specifically:

* Ensures the seven default rule rows always exist (so users don't
  have to add seven rows manually after install).
* Rejects duplicate rules for the same DocType.

Seeding also runs from the install patch (``patches/v1_0/seed_backdating_rules.py``)
so the rules exist *before* the user ever opens the page; this
controller's seeding is the safety net for any path that bypasses the
patch (e.g. fresh ``after_install``).
"""

import frappe
from frappe import _
from frappe.model.document import Document


SUPPORTED_DOCTYPES = (
    "Payment Voucher",
    "Receipt Voucher",
    "Ex Student Receipt",
    "Journal Entry",
    "Purchase Order",
    "Purchase Receipt",
    "Purchase Invoice",
)


class DuxBackdatingSettings(Document):

    def before_save(self):
        self._ensure_default_rules()
        self._reject_duplicate_rules()

    def _ensure_default_rules(self):
        existing = {r.target_doctype for r in (self.rules or [])
                     if r.target_doctype}
        for dt in SUPPORTED_DOCTYPES:
            if dt not in existing:
                self.append("rules", {
                    "target_doctype":       dt,
                    "allow_backdating":     0,
                    "max_days_back":        0,
                    "allow_forward_dating": 0,
                    "max_days_forward":     0,
                })

    def _reject_duplicate_rules(self):
        seen = set()
        for r in self.rules or []:
            if not r.target_doctype:
                continue
            if r.target_doctype in seen:
                frappe.throw(
                    _("Duplicate rule for DocType '{0}'. Each "
                      "controlled DocType must appear at most once.")
                    .format(r.target_doctype)
                )
            seen.add(r.target_doctype)
