import frappe
from frappe import _
from frappe.utils import flt, getdate, formatdate


@frappe.whitelist()
def get_ledger_statement(company, account, from_date, to_date):
	"""
	Return Tally-style ledger statement data.
	Includes opening balance, GL Entries with running balance, closing balance.
	"""
	if not all([company, account, from_date, to_date]):
		frappe.throw(_("Company, Account, From Date and To Date are all required"))

	from_date = getdate(from_date)
	to_date = getdate(to_date)

	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	# ── Opening Balance ───────────────────────────────────────────────────────
	ob_row = frappe.db.sql("""
		SELECT
			COALESCE(SUM(debit_in_account_currency),  0) AS total_debit,
			COALESCE(SUM(credit_in_account_currency), 0) AS total_credit
		FROM `tabGL Entry`
		WHERE account      = %(account)s
		  AND company      = %(company)s
		  AND posting_date < %(from_date)s
		  AND is_cancelled = 0
	""", {"account": account, "company": company, "from_date": from_date}, as_dict=True)

	ob_net = flt(ob_row[0].total_debit) - flt(ob_row[0].total_credit) if ob_row else 0.0

	# ── Period GL Entries ─────────────────────────────────────────────────────
	entries = frappe.db.sql("""
		SELECT
			gle.posting_date,
			gle.voucher_type,
			gle.voucher_no,
			gle.against,
			gle.debit_in_account_currency  AS debit,
			gle.credit_in_account_currency AS credit,
			gle.remarks,
			gle.party_type,
			gle.party,
			gle.creation,

			CASE
				WHEN gle.voucher_type = 'Payment Entry' THEN pe.custom_source_voucher_doctype
				WHEN gle.voucher_type = 'Journal Entry' THEN je.custom_source_voucher_doctype
				ELSE NULL
			END AS source_doctype,

			CASE
				WHEN gle.voucher_type = 'Payment Entry' THEN pe.custom_source_voucher
				WHEN gle.voucher_type = 'Journal Entry' THEN je.custom_source_voucher
				ELSE NULL
			END AS source_voucher,

			CASE
				WHEN gle.voucher_type = 'Payment Entry' THEN pe.payment_type
				ELSE NULL
			END AS payment_type

		FROM `tabGL Entry` gle

		LEFT JOIN `tabPayment Entry` pe
			   ON pe.name = gle.voucher_no
			  AND gle.voucher_type = 'Payment Entry'

		LEFT JOIN `tabJournal Entry` je
			   ON je.name = gle.voucher_no
			  AND gle.voucher_type = 'Journal Entry'

		WHERE gle.account      = %(account)s
		  AND gle.company      = %(company)s
		  AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  AND gle.is_cancelled = 0

		ORDER BY gle.posting_date, gle.creation
	""", {
		"account":   account,
		"company":   company,
		"from_date": from_date,
		"to_date":   to_date,
	}, as_dict=True)

	# ── Build rows with running balance ───────────────────────────────────────
	running  = ob_net
	total_dr = 0.0
	total_cr = 0.0
	rows     = []

	for e in entries:
		dr = flt(e.debit)
		cr = flt(e.credit)
		running  += (dr - cr)
		total_dr += dr
		total_cr += cr

		display_type, display_vch, vch_url = _resolve_voucher(e)

		prefix = "To" if dr > 0 else "By"

		if e.party:
			contra = e.party
		else:
			contra = _clean_against(e.against or "")

		rows.append({
			"posting_date":  formatdate(e.posting_date, "dd-MMM-yy"),
			"prefix":        prefix,
			"contra":        contra,
			"voucher_type":  display_type,
			"voucher_no":    display_vch,
			"voucher_url":   vch_url,
			"debit":         dr,
			"credit":        cr,
			"balance":       abs(running),
			"balance_type":  "Dr" if running >= 0 else "Cr",
			"remarks":       (e.remarks or "").strip(),
		})

	closing = running

	# ── Account meta ──────────────────────────────────────────────────────────
	acc_meta = frappe.db.get_value(
		"Account", account,
		["account_name", "account_type", "root_type"],
		as_dict=True
	) or {}

	return {
		"company":         company,
		"account":         account,
		"account_name":    acc_meta.get("account_name", account),
		"account_type":    acc_meta.get("account_type", ""),
		"from_date":       formatdate(from_date, "dd-MMM-yyyy"),
		"to_date":         formatdate(to_date,   "dd-MMM-yyyy"),
		"opening_balance": abs(ob_net),
		"opening_type":    "Dr" if ob_net >= 0 else "Cr",
		"closing_balance": abs(closing),
		"closing_type":    "Dr" if closing >= 0 else "Cr",
		"total_debit":     total_dr,
		"total_credit":    total_cr,
		"rows":            rows,
		"row_count":       len(rows),
	}


@frappe.whitelist()
def search_ledger(company, search_txt=""):
	"""
	Combined search across Account master, Customer, Supplier, Employee.
	Returns {value, label, meta} for the custom dropdown.
	value = actual account name in GL Entry (what gets passed to get_ledger_statement)
	label = human-readable display name
	meta  = account type and code shown below label
	"""
	if not company:
		return []

	like = "%" + (search_txt or "") + "%"
	results = []

	# 1. Account master (leaf nodes for this company)
	accounts = frappe.db.sql("""
		SELECT name, account_name, account_type
		FROM `tabAccount`
		WHERE company  = %(company)s
		  AND is_group = 0
		  AND disabled = 0
		  AND (name LIKE %(like)s OR account_name LIKE %(like)s)
		ORDER BY name
		LIMIT 20
	""", {"company": company, "like": like}, as_dict=True)

	for a in accounts:
		results.append({
			"value": a.name,
			"label": a.account_name,
			"meta":  (a.account_type or "Account") + "  ·  " + a.name,
		})

	# 2. Customers — map to their receivable account
	if len(results) < 25:
		customers = frappe.db.sql("""
			SELECT name, customer_name
			FROM `tabCustomer`
			WHERE disabled = 0
			  AND (name LIKE %(like)s OR customer_name LIKE %(like)s)
			ORDER BY name LIMIT 8
		""", {"like": like}, as_dict=True)

		for c in customers:
			acc = frappe.db.get_value(
				"Party Account",
				{"parent": c.name, "company": company, "parenttype": "Customer"},
				"account"
			) or frappe.get_cached_value("Company", company, "default_receivable_account")
			if acc:
				results.append({
					"value": acc,
					"label": c.customer_name + "  (Customer)",
					"meta":  "Receivable  ·  " + acc,
				})

	# 3. Suppliers — map to their payable account
	if len(results) < 30:
		suppliers = frappe.db.sql("""
			SELECT name, supplier_name
			FROM `tabSupplier`
			WHERE disabled = 0
			  AND (name LIKE %(like)s OR supplier_name LIKE %(like)s)
			ORDER BY name LIMIT 8
		""", {"like": like}, as_dict=True)

		for s in suppliers:
			acc = frappe.db.get_value(
				"Party Account",
				{"parent": s.name, "company": company, "parenttype": "Supplier"},
				"account"
			) or frappe.get_cached_value("Company", company, "default_payable_account")
			if acc:
				results.append({
					"value": acc,
					"label": s.supplier_name + "  (Supplier)",
					"meta":  "Payable  ·  " + acc,
				})

	return results[:30]


def _resolve_voucher(e):
	"""Map GL Entry row to display type, voucher number, and desk URL."""
	src_dt  = (e.get("source_doctype") or "").strip()
	src_vch = (e.get("source_voucher") or "").strip()
	pmt     = (e.get("payment_type")   or "").strip()
	vt      = e.voucher_type
	vno     = e.voucher_no

	if src_dt == "Payment Voucher" and src_vch:
		label = "Contra Entry" if pmt == "Internal Transfer" else "Payment Voucher"
		return label, src_vch, "/desk/payment-voucher/" + src_vch

	if src_dt == "Receipt Voucher" and src_vch:
		return "Receipt Voucher", src_vch, "/desk/receipt-voucher/" + src_vch

	if vt == "Journal Entry":
		return "Journal Entry", vno, "/desk/journal-entry/" + vno

	if vt == "Payment Entry":
		if pmt == "Internal Transfer":
			label = "Contra Entry"
		elif pmt == "Receive":
			label = "Receipt Entry"
		else:
			label = "Payment Entry"
		return label, vno, "/desk/payment-entry/" + vno

	slug = vt.lower().replace(" ", "-")
	return vt, vno, "/desk/" + slug + "/" + vno


def _clean_against(against_str):
	"""Return single account or 'Various' for comma-separated list."""
	parts = [a.strip() for a in against_str.split(",") if a.strip()]
	if not parts:
		return ""
	if len(parts) == 1:
		return parts[0]
	return "Various"
