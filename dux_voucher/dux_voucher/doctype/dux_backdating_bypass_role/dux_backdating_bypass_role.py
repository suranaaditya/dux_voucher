import frappe
from frappe.model.document import Document


class DuxBackdatingBypassRole(Document):
    """Child row in the Dux Backdating Settings ``bypass_roles`` table —
    a single Role link rendered as a multi-select pill in the parent's
    Table MultiSelect field. No additional logic; presence of any row
    whose role matches a current-user role short-circuits the policy
    check in ``api/backdating.enforce``."""
    pass
