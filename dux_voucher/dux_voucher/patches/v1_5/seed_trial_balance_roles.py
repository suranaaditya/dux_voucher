"""Create the two Trial Balance roles.

Access was previously gated on ERPNext's generic accounting roles, which
meant every Accounts User saw the report whether or not anyone intended
it. These two exist so access can be granted deliberately, one user at a
time, without handing out Accounts Manager.

    Dux Trial Balance          open and read the report
    Dux Trial Balance Manager  the above, plus rebuilding the aggregate

The split matters because a rebuild is not a read. It re-aggregates every
trust company across the full GL span and takes minutes; it should not be
something any reader can set off.

Idempotent — safe to re-run.
"""

import frappe

ROLES = (
    ("Dux Trial Balance",
     "Open the Dux Trial Balance report and page. Company visibility is "
     "still governed by User Permissions on Company."),
    ("Dux Trial Balance Manager",
     "Everything Dux Trial Balance allows, plus rebuilding the monthly "
     "aggregate."),
)


def execute():
    created = 0
    for name, desc in ROLES:
        if frappe.db.exists("Role", name):
            continue
        doc = frappe.new_doc("Role")
        doc.role_name = name
        doc.desk_access = 1
        # Not restricted to the owner's own documents — this is a reporting
        # role, and the company scoping it needs already happens server-side.
        doc.disabled = 0
        doc.flags.ignore_permissions = True
        doc.insert()
        created += 1
    if created:
        frappe.db.commit()
    print(f"[dux_voucher] seed_trial_balance_roles: created {created} role(s)")
