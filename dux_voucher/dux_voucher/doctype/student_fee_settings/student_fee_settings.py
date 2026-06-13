"""Student Fee Settings — site-wide config for the admission-fee module.

Single doctype. Currently holds one setting: the income account credited
when a student's retained (partly-refunded / forfeited) admission fee is
booked as income. Resolved by
``dux_voucher.dux_voucher.api.student_fee.get_retained_income_account``.
"""

import frappe
from frappe.model.document import Document


class StudentFeeSettings(Document):
    pass
