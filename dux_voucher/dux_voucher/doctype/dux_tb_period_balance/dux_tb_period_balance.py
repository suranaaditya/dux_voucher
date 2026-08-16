"""Dux TB Period Balance — the monthly aggregate behind the fast path.

Read-only from a user's point of view: rows are written only by
``api.tb_aggregate.rebuild``. ``in_create`` blocks creation through the UI,
and no role is granted write or delete, because a hand-edited aggregate
that silently disagrees with the GL is worse than no aggregate at all.
"""

from frappe.model.document import Document


class DuxTBPeriodBalance(Document):
    pass
