import frappe
from frappe import _
from frappe.model.document import Document


class DuxBackdatingRule(Document):
    """One rule = posting-date policy for a single target DocType.

    Validation here is intentionally light — the heavy lifting (checking
    each saved document against the policy) lives in
    ``dux_voucher.dux_voucher.api.backdating.enforce`` and runs as a
    ``validate`` doc_event on every controlled doctype.
    """

    def validate(self):
        if (self.max_days_back or 0) < 0:
            frappe.throw(_("Max Days Back cannot be negative."))
        if (self.max_days_forward or 0) < 0:
            frappe.throw(_("Max Days Forward cannot be negative."))
