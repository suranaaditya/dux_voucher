import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dux_voucher.dux_voucher.api.utils import (
	_submit_doc,
	_safe_cancel,
)


class InterCompanyTransfer(Document):

	# ──────────────────────────────────────────────────────────────
	# Validate
	# ──────────────────────────────────────────────────────────────
	def validate(self):
		self._validate_basics()

	def _validate_basics(self):
		if not self.company:
			frappe.throw(_("Company is required"))
		if not self.transaction_date:
			frappe.throw(_("Date is required"))
		if not flt(self.amount) or flt(self.amount) <= 0:
			frappe.throw(_("Amount must be greater than zero"))

		if self.transfer_type == "Payment":
			if not self.paid_from_account:
				frappe.throw(_("Paid From Account is required"))
			if not self.paid_to_company:
				frappe.throw(_("Paid To Company is required"))
			if self.paid_to_company == self.company:
				frappe.throw(_("Paid To Company cannot be the same as your company"))
			self._validate_account_belongs_to_company(
				self.paid_from_account, self.company, "Paid From Account"
			)
		else:
			if not self.received_in_account:
				frappe.throw(_("Received In Account is required"))
			if not self.received_from_company:
				frappe.throw(_("Received From Company is required"))
			if self.received_from_company == self.company:
				frappe.throw(_("Received From Company cannot be the same as your company"))
			self._validate_account_belongs_to_company(
				self.received_in_account, self.company, "Received In Account"
			)

	def _validate_account_belongs_to_company(self, account, company, label):
		account_company = frappe.db.get_value("Account", account, "company")
		if account_company != company:
			frappe.throw(
				_("{0} '{1}' does not belong to {2}").format(label, account, company)
			)

	# ──────────────────────────────────────────────────────────────
	# On Submit — STAGE 1
	# Creates JE only in the initiating company.
	# Branch & Division accounting:
	#
	#   Payment (GHRCE pays GHRUA):
	#     DR  Branch & Division - GHRUA  (asset: GHRUA owes us)
	#     CR  Bank/Cash
	#
	#   Receipt (GHRCE receives from GHRUA):
	#     DR  Bank/Cash
	#     CR  Branch & Division - GHRUA  (liability: we received from GHRUA)
	# ──────────────────────────────────────────────────────────────
	def on_submit(self):
		try:
			from_je_name = self._create_initiator_je()
		except frappe.ValidationError:
			raise
		except Exception as e:
			frappe.db.rollback()
			frappe.throw(_("Error creating journal entry: {0}").format(str(e)))

		frappe.db.set_value("Inter-Company Transfer", self.name, {
			"from_je": from_je_name,
			"mirror_status": "Pending Review",
		})

	# ──────────────────────────────────────────────────────────────
	# On Cancel
	# ──────────────────────────────────────────────────────────────
	def on_cancel(self):
		if self.to_je:
			_safe_cancel("Journal Entry", self.to_je)
		if self.from_je:
			_safe_cancel("Journal Entry", self.from_je)
		frappe.db.set_value("Inter-Company Transfer", self.name, "mirror_status", "Cancelled")

	# ──────────────────────────────────────────────────────────────
	# STAGE 2 — User B confirms and selects their account
	#
	#   Payment mirror (GHRUA confirms receipt from GHRCE):
	#     DR  Bank/Cash              ← User B selects this
	#     CR  Branch & Division - GHRCE  (GHRCE paid us — clear the liability)
	#
	#   Receipt mirror (GHRUA confirms payment to GHRCE):
	#     DR  Branch & Division - GHRCE  (GHRCE received from us — they owe us)
	#     CR  Bank/Cash              ← User B selects this
	# ──────────────────────────────────────────────────────────────
	@frappe.whitelist()
	def confirm_mirror(self, to_account):
		if self.docstatus != 1:
			frappe.throw(_("Inter-Company Transfer must be submitted first"))
		if self.mirror_status == "Completed":
			frappe.throw(_("This transfer has already been confirmed"))
		if self.mirror_status == "Cancelled":
			frappe.throw(_("This transfer has been cancelled"))

		other_company = (
			self.paid_to_company
			if self.transfer_type == "Payment"
			else self.received_from_company
		)

		self._validate_user_can_confirm(other_company)
		self._validate_account_belongs_to_company(to_account, other_company, "Account")

		account_type = frappe.db.get_value("Account", to_account, "account_type")
		if account_type not in ("Bank", "Cash"):
			frappe.throw(_("Please select a Bank or Cash type account"))

		try:
			to_je_name = self._create_mirror_je(to_account, other_company)
		except frappe.ValidationError:
			raise
		except Exception as e:
			frappe.db.rollback()
			frappe.throw(_("Error creating mirror journal entry: {0}").format(str(e)))

		frappe.db.set_value("Inter-Company Transfer", self.name, {
			"to_je": to_je_name,
			"mirror_status": "Completed",
		})
		return to_je_name

	# ──────────────────────────────────────────────────────────────
	# Stage 1 JE — Initiating company
	# ──────────────────────────────────────────────────────────────
	def _create_initiator_je(self):
		other_company = (
			self.paid_to_company
			if self.transfer_type == "Payment"
			else self.received_from_company
		)

		# Get Branch & Division account in THIS company representing the other company
		branch_account = self._get_ic_account(self.company, other_company)

		if self.transfer_type == "Payment":
			# DR Branch & Division - [other company]  /  CR Bank/Cash
			je = self._build_je(
				company=self.company,
				debit_account=branch_account,
				credit_account=self.paid_from_account,
				amount=flt(self.amount),
			)
		else:
			# DR Bank/Cash  /  CR Branch & Division - [other company]
			je = self._build_je(
				company=self.company,
				debit_account=self.received_in_account,
				credit_account=branch_account,
				amount=flt(self.amount),
			)

		_submit_doc(je)
		return je.name

	# ──────────────────────────────────────────────────────────────
	# Stage 2 JE — Other company mirror
	# ──────────────────────────────────────────────────────────────
	def _create_mirror_je(self, to_account, other_company):
		# Get Branch & Division account in OTHER company representing THIS company
		branch_account = self._get_ic_account(other_company, self.company)

		if self.transfer_type == "Payment":
			# DR Bank/Cash  /  CR Branch & Division - [this company]
			je = self._build_je(
				company=other_company,
				debit_account=to_account,
				credit_account=branch_account,
				amount=flt(self.amount),
				remark_suffix=f"Confirmed by {frappe.session.user}",
			)
		else:
			# DR Branch & Division - [this company]  /  CR Bank/Cash
			je = self._build_je(
				company=other_company,
				debit_account=branch_account,
				credit_account=to_account,
				amount=flt(self.amount),
				remark_suffix=f"Confirmed by {frappe.session.user}",
			)

		_submit_doc(je)
		return je.name

	# ──────────────────────────────────────────────────────────────
	# Helpers
	# ──────────────────────────────────────────────────────────────
	def _build_je(self, company, debit_account, credit_account, amount, remark_suffix=""):
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = company
		je.posting_date = self.transaction_date
		je.cheque_no = self.reference_no or ""
		je.cheque_date = self.reference_date or None
		je.user_remark = (self.remarks or "") + (f"\n{remark_suffix}" if remark_suffix else "")
		je.custom_source_voucher_doctype = "Inter-Company Transfer"
		je.custom_source_voucher = self.name

		je.append("accounts", {
			"account": debit_account,
			"debit_in_account_currency": amount,
			"credit_in_account_currency": 0,
		})
		je.append("accounts", {
			"account": credit_account,
			"debit_in_account_currency": 0,
			"credit_in_account_currency": amount,
		})
		return je

	def _validate_user_can_confirm(self, other_company):
		user = frappe.session.user
		roles = frappe.get_roles(user)
		if "System Manager" in roles:
			return
		permitted = frappe.db.get_all(
			"User Permission",
			filters={"user": user, "allow": "Company", "for_value": other_company},
			fields=["name"],
			limit=1,
		)
		if not permitted:
			frappe.throw(_(
				"You do not have permission for <b>{0}</b>.<br>"
				"Only an accountant assigned to {0} can confirm this transfer."
			).format(other_company))

	def _get_ic_account(self, company, other_company):
		"""
		Find the Branch & Division account in `company`'s COA that
		represents `other_company`.

		Uses the Inter-Company Transfer Settings mapping table.
		The mapping stores: other_company → branch_account_name.
		We then look up that account name scoped to `company`.

		Example:
		  _get_ic_account("GHRCE", "GHRUA")
		  → Settings says GHRUA maps to account name "GH Raisoni University Amravati"
		  → Returns the account "GH Raisoni University Amravati - GHRCE"
		"""
		# Step 1 — Get the account label from settings mapping
		account_label = frappe.db.get_value(
			"IC Company Account Mapping",
			{"parent": "Inter-Company Transfer Settings", "company": other_company},
			"account_label",
		)

		if not account_label:
			frappe.throw(_(
				"No Branch & Division account mapping found for <b>{0}</b>.<br><br>"
				"Please go to <b>Accounting → Inter-Company Transfer Settings</b> "
				"and add a mapping for <b>{0}</b>."
			).format(other_company))

		# Step 2 — Resolve the Branch / Divisions group label (configurable per deployment)
		branch_group_label = frappe.db.get_single_value(
			"Inter-Company Transfer Settings", "branch_group_name"
		) or "Branch / Divisions"

		# Step 3 — Find the Branch / Divisions group account in `company`'s COA
		branch_group = frappe.db.get_value(
			"Account",
			{
				"account_name": branch_group_label,
				"company": company,
				"is_group": 1,
			},
			"name",
		)

		if not branch_group:
			frappe.throw(_(
				"Could not find <b>{0}</b> group account in <b>{1}</b>'s "
				"Chart of Accounts.<br><br>"
				"Please ensure a group account named '{0}' exists under "
				"Current Assets in {1}'s COA, or update the group name in "
				"<b>Inter-Company Transfer Settings</b>."
			).format(branch_group_label, company))

		# Step 4 — Find the account scoped to `company` under that group, matching account_label
		match = frappe.db.get_value(
			"Account",
			{
				"account_name": account_label,
				"parent_account": branch_group,
				"company": company,
				"is_group": 0,
				"disabled": 0,
			},
			"name",
		)
		if match:
			return match

		frappe.throw(_(
			"Could not find a Branch & Division account named <b>{0}</b> "
			"under <b>{1}</b> in <b>{2}</b>'s Chart of Accounts.<br><br>"
			"Please ensure this account exists, or update the mapping "
			"in <b>Inter-Company Transfer Settings</b>."
		).format(account_label, branch_group_label, company))
