"""
Whitelisted entry point for the formatted Trial Balance export.

Calls the standard ERPNext Trial Balance ``execute()`` to obtain the
data, hands ``columns`` and ``rows`` to :func:`builder.build_formatted_tb`,
saves the resulting xlsx as a private File doctype, and returns the
download URL to the client script.

The API never re-implements accounting — it is a thin glue layer
between the standard report and the v5 presentation builder.
"""

import json

import frappe
from frappe import _
from frappe.utils.file_manager import save_file

from dux_voucher.formatted_reports.trial_balance.builder import (
    build_formatted_tb,
)


@frappe.whitelist()
def export_formatted_tb(filters):
    """Generate the formatted Trial Balance and return a private File URL.

    Parameters
    ----------
    filters : dict | str
        The TB filter set from the standard report. Frappe will pass it
        as a JSON string when the call originates from JS; we accept
        both shapes for ergonomics.

    Returns
    -------
    dict
        ``{"file_url": <str>, "file_name": <str>}`` — the client opens
        ``file_url`` to trigger the browser download.
    """
    if isinstance(filters, str):
        filters = json.loads(filters)
    elif filters is None:
        filters = {}

    company = filters.get("company")
    if not company:
        frappe.throw(_("Please select a Company before downloading."))

    # Reuse the standard report's data layer — never recompute totals.
    from erpnext.accounts.report.trial_balance.trial_balance import execute
    columns, rows = execute(filters)

    if not rows:
        frappe.throw(_(
            "The Trial Balance report returned no rows for these filters."
        ))

    company_name = (frappe.db.get_value("Company", company, "company_name")
                     or company)
    abbr         = frappe.db.get_value("Company", company, "abbr") or ""

    xlsx_bytes, filename = build_formatted_tb(
        filters, columns, rows,
        company_name=company_name,
        abbr=abbr,
    )

    file_doc = save_file(
        filename,
        xlsx_bytes,
        dt=None, dn=None,            # not attached to a specific document
        is_private=1,
    )
    return {"file_url": file_doc.file_url, "file_name": file_doc.file_name}
