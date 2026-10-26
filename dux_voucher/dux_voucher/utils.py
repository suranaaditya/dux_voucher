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
    """When a Journal Entry is cancelled directly, cancel its parent voucher.

    Special case — a retained-fee income-booking JE is referenced the OTHER
    way (Student Fee Refund.income_je) rather than via custom_source_voucher.
    Cancelling it must NOT cancel the refund; it just clears the booking so
    the operator can re-book. Handle that first, then return.
    """
    if frappe.flags.in_dux_voucher_cancel:
        return

    booked_refund = frappe.db.get_value(
        "Student Fee Refund", {"income_je": doc.name}, "name")
    if booked_refund:
        frappe.db.set_value("Student Fee Refund", booked_refund, {
            "income_booked": 0,
            "income_je": None,
            "income_amount": 0,
            "income_booked_date": None,
        })
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

    # All or nothing. The parent's own cancel cancels its OTHER backend
    # entries (a Student Journal Voucher's second company, a PV's sibling
    # PEs); if any of that fails half-way, swallowing the error would commit
    # a voucher or JE marked Cancelled whose ledger lines are still live.
    # Roll the parent back and refuse the cancel the user started instead.
    frappe.flags.in_dux_voucher_cancel = True
    frappe.db.savepoint("dux_parent_cancel")
    try:
        voucher = frappe.get_doc(doctype, name)
        voucher.flags.ignore_permissions = True
        voucher.cancel()
    except Exception as e:
        frappe.db.rollback(save_point="dux_parent_cancel")
        frappe.throw(
            _("This entry belongs to {0} {1}, which could not be cancelled "
              "with it, so nothing was cancelled. Reason: {2}")
            .format(doctype, name, frappe.utils.strip_html(str(e)))
        )
    finally:
        frappe.flags.in_dux_voucher_cancel = False