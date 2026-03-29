import frappe
from frappe import _
from dux_voucher.dux_voucher.api.utils import _detect_party_type


@frappe.whitelist()
def get_party_type(party_name):
    """Auto-detect if party is Customer, Supplier or Employee."""
    return _detect_party_type(party_name)


@frappe.whitelist()
def get_party_details(party_name):
    """
    Return party_type and display name for a given party name.
    Called from JS when user selects a party in the search dialog.
    """
    party_type = _detect_party_type(party_name)
    if not party_type:
        return None

    name_field_map = {
        "Customer": "customer_name",
        "Supplier": "supplier_name",
        "Employee": "employee_name"
    }
    name_field = name_field_map.get(party_type)
    display_name = frappe.db.get_value(
        party_type, party_name, name_field
    ) or ""

    return {
        "party_type": party_type,
        "party_name": display_name
    }


@frappe.whitelist()
def search_party(doctype, txt, searchfield, start, page_len, filters):
    """
    Search across Customer, Supplier and Employee in one query.
    Used as custom search for Party field in party rows table.
    Returns rows of (name, display_name, party_type).
    """
    txt = "%" + (txt or "") + "%"
    per_dt = max(1, int(page_len) // 3 + 1)
    results = []

    for dt, name_field, condition in (
        ("Customer", "customer_name", "disabled = 0"),
        ("Supplier", "supplier_name", "disabled = 0"),
        ("Employee", "employee_name", "status = 'Active'"),
    ):
        rows = frappe.db.sql(
            """
            SELECT name, `{nf}`, '{dt}' as party_type
            FROM `tab{dt}`
            WHERE (`{nf}` LIKE %(txt)s OR name LIKE %(txt)s)
            AND {cond}
            ORDER BY name
            LIMIT %(pl)s
            """.format(dt=dt, nf=name_field, cond=condition),
            {"txt": txt, "pl": per_dt},
        )
        results.extend(rows)

    return results[:int(page_len)]


@frappe.whitelist()
def get_mop_account_type(mode_of_payment):
    """
    Return account type (Bank/Cash) for a Mode of Payment.
    Used by JS to filter Paid From Account dropdown.
    """
    if not mode_of_payment:
        return None
    return frappe.db.get_value(
        "Mode of Payment", mode_of_payment, "type"
    )


@frappe.whitelist()
def validate_backend_entry(voucher_doctype, voucher_name):
    """
    Dry-run validation of backend entry before submitting.
    Returns any errors so JS can show them to user.
    """
    errors = []
    try:
        doc = frappe.get_doc(voucher_doctype, voucher_name)
        doc.run_method("validate")
    except frappe.ValidationError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(str(e))

    return {"errors": errors}