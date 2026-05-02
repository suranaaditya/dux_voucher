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
