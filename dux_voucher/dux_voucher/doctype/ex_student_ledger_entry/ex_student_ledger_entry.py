# Copyright (c) 2026, Dux Digitech and contributors
# For license information, please see license.txt

from contextlib import contextmanager

import frappe
from frappe import _
from frappe.model.document import Document

# The vouchers that post here. Each inserts its rows from its own on_submit
# (inside ``posting_ledger_rows``) and flags them cancelled with SQL from
# its on_cancel.
POSTING_VOUCHERS = (
	"Ex Student Opening Batch",
	"Ex Student Opening Adjustment",
	"Ex Student Receipt",
	"Ex Student Refund",
	"Ex Student Writeoff",
)


@contextmanager
def posting_ledger_rows(voucher):
	"""Mark the voucher whose rows are being inserted. A request-local
	flag: no client, API call or Data Import can set it."""
	frappe.flags.ex_student_posting = (voucher.doctype, voucher.name)
	try:
		yield
	finally:
		frappe.flags.ex_student_posting = None


def require_cancel_right(voucher):
	"""From each voucher's before_cancel. Cancelling a voucher's journal
	entry cancels the voucher too (utils._cancel_parent_voucher), with
	permissions ignored — so whoever may cancel a Journal Entry could
	reverse a whole Opening Batch. Ex Student vouchers are cancelled only by
	those allowed to cancel them (Accounts Manager, System Manager),
	wherever the cancel starts."""
	if frappe.flags.in_dux_voucher_cancel:
		frappe.has_permission(voucher.doctype, "cancel", doc=voucher, throw=True)


def delete_cancelled_ledger_rows(voucher):
	"""From a voucher's on_trash. Frappe only deletes a cancelled voucher,
	and its rows still link to it, so they go with it — they no longer
	count towards any balance."""
	frappe.db.delete("Ex Student Ledger Entry", {
		"voucher_type": voucher.doctype, "voucher_no": voucher.name, "is_cancelled": 1})


class ExStudentLedgerEntry(Document):
	"""One student's share of a posted voucher — the record the student's
	balance is summed from. The GL holds only the voucher's netted journal,
	so a row changed by hand moves the balance without moving the books.
	Only the voucher posting it may create one, and nobody may edit or
	delete one: correct the voucher (cancel it, or post an Opening
	Adjustment) instead. Role permissions already say read-only; this also
	holds against Administrator, the API and Data Import."""

	def validate(self):
		if not self.is_new():
			frappe.throw(_(
				"Ex Student Ledger Entries cannot be edited. To change a balance, "
				"cancel the voucher that posted it or post an Ex Student Opening Adjustment."
			), title=_("Read-only"))
		if (self.voucher_type, self.voucher_no) != frappe.flags.get("ex_student_posting"):
			frappe.throw(_("Ex Student Ledger Entries are posted by their voucher on submit"))

	def on_trash(self):
		frappe.throw(_(
			"Ex Student Ledger Entries cannot be deleted. Cancel the voucher that posted it instead."
		), title=_("Read-only"))
