import frappe

def execute(filters=None):
    columns = [
        {"label": "ID", "fieldname": "name", "fieldtype": "Link", "options": "Inter-Company Transfer", "width": 180},
        {"label": "Transfer Type", "fieldname": "transfer_type", "fieldtype": "Data", "width": 120},
        {"label": "Company", "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 220},
        {"label": "Amount", "fieldname": "amount", "fieldtype": "Currency", "width": 140},
        {"label": "Date", "fieldname": "transaction_date", "fieldtype": "Date", "width": 110},
        {"label": "Paid To Company", "fieldname": "paid_to_company", "fieldtype": "Link", "options": "Company", "width": 220},
        {"label": "Received From Company", "fieldname": "received_from_company", "fieldtype": "Link", "options": "Company", "width": 220},
        {"label": "Reference No", "fieldname": "reference_no", "fieldtype": "Data", "width": 130},
        {"label": "Mirror Status", "fieldname": "mirror_status", "fieldtype": "Data", "width": 130},
    ]

    user = frappe.session.user
    roles = frappe.get_roles(user)

    if "System Manager" in roles:
        data = frappe.get_all("Inter-Company Transfer",
            filters={"docstatus": 1, "mirror_status": "Pending Review"},
            fields=["name", "transfer_type", "company", "amount", "transaction_date",
                    "paid_to_company", "received_from_company", "reference_no", "mirror_status"],
            order_by="transaction_date desc")
    else:
        perms = frappe.get_all("User Permission",
            filters={"user": user, "allow": "Company"},
            fields=["for_value"])
        user_companies = [p.for_value for p in perms]
        if not user_companies:
            return columns, []

        placeholders = ", ".join(["%s"] * len(user_companies))
        data = frappe.db.sql(f"""
            SELECT name, transfer_type, company, amount, transaction_date,
                   paid_to_company, received_from_company, reference_no, mirror_status
            FROM `tabInter-Company Transfer`
            WHERE docstatus = 1
              AND mirror_status = 'Pending Review'
              AND (
                  paid_to_company IN ({placeholders})
                  OR received_from_company IN ({placeholders})
              )
            ORDER BY transaction_date DESC
        """, tuple(user_companies) * 2, as_dict=True)

    return columns, data
