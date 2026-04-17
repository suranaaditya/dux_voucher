import frappe
from frappe import _


def on_payment_entry_cancel(doc, method):
    """When a Payment Entry is cancelled directly, cancel its parent voucher."""
    if frappe.flags.in_dux_voucher_cancel:
        return

    voucher_doctype = doc.get("custom_source_voucher_doctype")
    voucher_name = doc.get("custom_source_voucher")

    if voucher_doctype and voucher_name:
        _cancel_parent_voucher(voucher_doctype, voucher_name)


def on_journal_entry_cancel(doc, method):
    """When a Journal Entry is cancelled directly, cancel its parent voucher."""
    if frappe.flags.in_dux_voucher_cancel:
        return

    voucher_doctype = doc.get("custom_source_voucher_doctype")
    voucher_name = doc.get("custom_source_voucher")

    if voucher_doctype and voucher_name:
        _cancel_parent_voucher(voucher_doctype, voucher_name)


def on_journal_entry_submit(doc, method):
    """When mirror JE is submitted by receiver, mark ICT as Completed."""
    voucher_doctype = doc.get("custom_source_voucher_doctype")
    voucher_name = doc.get("custom_source_voucher")
    if voucher_doctype == "Inter-Company Transfer" and voucher_name:
        from dux_voucher.dux_voucher.api.ic_transfer_api import mark_mirror_complete
        mark_mirror_complete(voucher_name)


def _cancel_parent_voucher(doctype, name):
    if not frappe.db.exists(doctype, name):
        return
    if frappe.db.get_value(doctype, name, "docstatus") != 1:
        return

    frappe.flags.in_dux_voucher_cancel = True
    try:
        voucher = frappe.get_doc(doctype, name)
        voucher.flags.ignore_permissions = True
        voucher.cancel()
    except Exception as e:
        frappe.log_error(
            title=_("Error cancelling {0} {1}").format(doctype, name),
            message=str(e)
        )
    finally:
        frappe.flags.in_dux_voucher_cancel = False