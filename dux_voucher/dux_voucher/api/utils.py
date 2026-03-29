import frappe
from frappe import _
from frappe.utils import flt


def _detect_party_type(party_name):
    """Return Customer, Supplier, Employee or None."""
    for dt in ("Customer", "Supplier", "Employee"):
        if frappe.db.exists(dt, party_name):
            return dt
    return None


def _get_party_account(party_type, party, company):
    """Get the ledger account for a party in a company."""
    if party_type == "Customer":
        acc = frappe.db.get_value(
            "Party Account",
            {"parent": party, "company": company, "parenttype": "Customer"},
            "account"
        )
        return acc or frappe.get_cached_value(
            "Company", company, "default_receivable_account"
        )
    elif party_type == "Supplier":
        acc = frappe.db.get_value(
            "Party Account",
            {"parent": party, "company": company, "parenttype": "Supplier"},
            "account"
        )
        return acc or frappe.get_cached_value(
            "Company", company, "default_payable_account"
        )
    elif party_type == "Employee":
        return frappe.get_cached_value(
            "Company", company, "default_payable_account"
        )
    return None


def _get_account_currency(account, company):
    """Get currency of an account, fallback to company currency."""
    currency = frappe.db.get_value("Account", account, "account_currency")
    return (
        currency
        or frappe.get_cached_value("Company", company, "default_currency")
        or "INR"
    )


def _get_account_type(account):
    """Get account type from Account master."""
    return frappe.db.get_value("Account", account, "account_type") or ""


def _validate_bank_cash_account(account, label):
    """Throw if account is not Bank or Cash type."""
    account_type = _get_account_type(account)
    if account_type not in ("Bank", "Cash"):
        frappe.throw(
            _("{0} must be a Bank or Cash type account. "
              "'{1}' is of type '{2}'").format(label, account, account_type)
        )


def _submit_doc(doc):
    """
    Insert and submit a document.
    Shows exact ERPNext error to user if anything fails.
    """
    try:
        doc.flags.ignore_permissions = True
        doc.insert()
        doc.submit()
    except frappe.ValidationError:
        raise
    except Exception as e:
        frappe.throw(
            _("Error while creating {0}: {1}").format(doc.doctype, str(e))
        )


def _safe_cancel(doctype, docname):
    """
    Cancel a backend document safely.
    Skips if already cancelled or doesn't exist.
    """
    if not docname:
        return
    if not frappe.db.exists(doctype, docname):
        return
    docstatus = frappe.db.get_value(doctype, docname, "docstatus")
    if docstatus != 1:
        return
    try:
        doc = frappe.get_doc(doctype, docname)
        doc.flags.ignore_permissions = True
        doc.cancel()
    except Exception as e:
        frappe.throw(
            _("Error cancelling {0} {1}: {2}").format(doctype, docname, str(e))
        )


def get_mop_type(mode_of_payment):
    """Return Mode of Payment type — Bank or Cash."""
    if not mode_of_payment:
        return "Bank"
    return frappe.db.get_value(
        "Mode of Payment", mode_of_payment, "type"
    ) or "Bank"