"""Child row of Student Fee Receipt — one fee head + amount.

Pure data row; the parent ``StudentFeeReceipt.validate`` checks that
the head belongs to the student's course and that the amount is
positive. No logic here.
"""

from frappe.model.document import Document


class StudentFeeReceiptHead(Document):
    pass
