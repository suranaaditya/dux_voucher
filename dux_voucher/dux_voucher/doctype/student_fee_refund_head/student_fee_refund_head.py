"""Child row of Student Fee Refund — one fee head + amount.

Pure data row; the parent ``StudentFeeRefund.validate`` checks that
the head belongs to the student's course and that the amount is
positive. No logic here. Mirror of ``Student Fee Receipt Head``.
"""

from frappe.model.document import Document


class StudentFeeRefundHead(Document):
    pass
