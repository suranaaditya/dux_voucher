"""Make Student an ERPNext Party Type.

A Journal Entry line can name any doctype as its party, but ERPNext's own
pickers (the party-type dropdown on a JE row, the General Ledger and Trial
Balance for Party filters) only offer doctypes that have a Party Type
record. This adds one for the app's Student doctype.

``account_type`` is Receivable — a student is, by nature, someone who owes
the institution fees. It does not make the student ledger account
Receivable: that account keeps its blank type (see api/student_ledger.py),
so ERPNext neither demands a party on it nor builds Payment Ledger rows.

Party Type has no create permission for any role, hence ignore_permissions.
Idempotent — a re-run is a no-op.
"""

import frappe


def execute():
    if frappe.db.exists("Party Type", "Student"):
        print("[dux_voucher] create_student_party_type: already present, no-op")
        return
    doc = frappe.new_doc("Party Type")
    doc.party_type = "Student"
    doc.account_type = "Receivable"
    doc.flags.ignore_permissions = True
    doc.insert()
    frappe.db.commit()
    print("[dux_voucher] create_student_party_type: created Party Type 'Student'")
