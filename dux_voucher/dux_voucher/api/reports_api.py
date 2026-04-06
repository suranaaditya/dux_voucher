import frappe
from frappe import _
from frappe.utils import flt, getdate, formatdate


@frappe.whitelist()
def get_ledger_statement(company, account, from_date, to_date,
						  party=None, party_type=None):
	"""
	Tally-style ledger statement.
	- If party + party_type are supplied  → filter GL Entry by party field
	  (shows all entries for that specific Customer / Supplier / Employee)
	- If only account is supplied          → filter GL Entry by account field
	"""
	if not all([company, account, from_date, to_date]):
		frappe.throw(_("Company, Account, From Date and To Date are all required"))

	from_date = getdate(from_date)
	to_date   = getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	use_party = bool(party and party_type)

	# ── Opening Balance ───────────────────────────────────────────────────────
	if use_party:
		ob_row = frappe.db.sql("""
			SELECT
				COALESCE(SUM(debit_in_account_currency),  0) AS total_debit,
				COALESCE(SUM(credit_in_account_currency), 0) AS total_credit
			FROM `tabGL Entry`
			WHERE party      = %(party)s
			  AND party_type = %(party_type)s
			  AND company    = %(company)s
			  AND posting_date < %(from_date)s
			  AND is_cancelled  = 0
		""", {"party": party, "party_type": party_type,
			  "company": company, "from_date": from_date}, as_dict=True)
	else:
		ob_row = frappe.db.sql("""
			SELECT
				COALESCE(SUM(debit_in_account_currency),  0) AS total_debit,
				COALESCE(SUM(credit_in_account_currency), 0) AS total_credit
			FROM `tabGL Entry`
			WHERE account      = %(account)s
			  AND company      = %(company)s
			  AND posting_date < %(from_date)s
			  AND is_cancelled  = 0
		""", {"account": account, "company": company,
			  "from_date": from_date}, as_dict=True)

	ob_net = (flt(ob_row[0].total_debit) - flt(ob_row[0].total_credit)
			  if ob_row else 0.0)

	# ── Period GL Entries ─────────────────────────────────────────────────────
	if use_party:
		where_clause = """
			gle.party      = %(party)s
			AND gle.party_type = %(party_type)s
			AND gle.company    = %(company)s
			AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND gle.is_cancelled = 0
		"""
		params = {"party": party, "party_type": party_type,
				  "company": company,
				  "from_date": from_date, "to_date": to_date}
	else:
		where_clause = """
			gle.account      = %(account)s
			AND gle.company  = %(company)s
			AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
			AND gle.is_cancelled = 0
		"""
		params = {"account": account, "company": company,
				  "from_date": from_date, "to_date": to_date}

	entries = frappe.db.sql("""
		SELECT
			gle.posting_date,
			gle.account,
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
				WHEN gle.voucher_type = 'Payment Entry'
					THEN pe.custom_source_voucher_doctype
				WHEN gle.voucher_type = 'Journal Entry'
					THEN je.custom_source_voucher_doctype
				ELSE NULL
			END AS source_doctype,

			CASE
				WHEN gle.voucher_type = 'Payment Entry'
					THEN pe.custom_source_voucher
				WHEN gle.voucher_type = 'Journal Entry'
					THEN je.custom_source_voucher
				ELSE NULL
			END AS source_voucher,

			CASE
				WHEN gle.voucher_type = 'Payment Entry'
					THEN pe.payment_type
				ELSE NULL
			END AS payment_type

		FROM `tabGL Entry` gle

		LEFT JOIN `tabPayment Entry` pe
			   ON pe.name = gle.voucher_no
			  AND gle.voucher_type = 'Payment Entry'

		LEFT JOIN `tabJournal Entry` je
			   ON je.name = gle.voucher_no
			  AND gle.voucher_type = 'Journal Entry'

		WHERE {where}

		ORDER BY gle.posting_date, gle.creation
	""".format(where=where_clause), params, as_dict=True)

	# ── Build rows ────────────────────────────────────────────────────────────
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

		# ICAI rule: account debited → "To", account credited → "By"
		prefix = "To" if dr > 0 else "By"

		# For party-mode, show account name as contra; else show party or against
		if use_party:
			contra = e.account or _clean_against(e.against or "")
		elif e.party:
			contra = e.party
		else:
			contra = _clean_against(e.against or "")

		rows.append({
			"posting_date": formatdate(e.posting_date, "dd-MMM-yy"),
			"prefix":       prefix,
			"contra":       contra,
			"voucher_type": display_type,
			"voucher_no":   display_vch,
			"voucher_url":  vch_url,
			"debit":        dr,
			"credit":       cr,
			"balance":      abs(running),
			"balance_type": "Dr" if running >= 0 else "Cr",
			"remarks":      (e.remarks or "").strip(),
		})

	closing = running

	# ── Account / Party meta ──────────────────────────────────────────────────
	if use_party:
		display_name = party
		acc_type     = party_type
	else:
		acc_meta = frappe.db.get_value(
			"Account", account,
			["account_name", "account_type"], as_dict=True
		) or {}
		display_name = acc_meta.get("account_name", account)
		acc_type     = acc_meta.get("account_type", "")

	return {
		"company":         company,
		"account":         account,
		"account_name":    display_name,
		"account_type":    acc_type,
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
	Search accounts AND parties (Customer/Supplier/Employee).
	Returns {value, label, meta, type, party_type, account} per item.
	  type = "account" → filter GL by account field
	  type = "party"   → filter GL by party field
	"""
	if not company:
		return []

	like = "%" + (search_txt or "") + "%"
	results = []

	# 1. Account master
	accounts = frappe.db.sql("""
		SELECT name, account_name, account_type
		FROM `tabAccount`
		WHERE company  = %(company)s
		  AND is_group = 0
		  AND disabled = 0
		  AND (name LIKE %(like)s OR account_name LIKE %(like)s)
		ORDER BY name LIMIT 15
	""", {"company": company, "like": like}, as_dict=True)

	for a in accounts:
		results.append({
			"type":       "account",
			"value":      a.name,
			"label":      a.account_name,
			"meta":       (a.account_type or "Account") + "  ·  " + a.name,
			"party_type": None,
			"account":    a.name,
		})

	# 2. Customers
	if len(results) < 25:
		customers = frappe.db.sql("""
			SELECT name, customer_name FROM `tabCustomer`
			WHERE disabled = 0
			  AND (name LIKE %(like)s OR customer_name LIKE %(like)s)
			ORDER BY name LIMIT 8
		""", {"like": like}, as_dict=True)

		for c in customers:
			acc = (frappe.db.get_value(
					"Party Account",
					{"parent": c.name, "company": company,
					 "parenttype": "Customer"}, "account")
				   or frappe.get_cached_value(
					"Company", company, "default_receivable_account"))
			results.append({
				"type":       "party",
				"value":      c.name,
				"label":      c.customer_name + "  (Customer)",
				"meta":       "Customer  ·  " + (acc or ""),
				"party_type": "Customer",
				"account":    acc or "",
			})

	# 3. Suppliers
	if len(results) < 30:
		suppliers = frappe.db.sql("""
			SELECT name, supplier_name FROM `tabSupplier`
			WHERE disabled = 0
			  AND (name LIKE %(like)s OR supplier_name LIKE %(like)s)
			ORDER BY name LIMIT 8
		""", {"like": like}, as_dict=True)

		for s in suppliers:
			acc = (frappe.db.get_value(
					"Party Account",
					{"parent": s.name, "company": company,
					 "parenttype": "Supplier"}, "account")
				   or frappe.get_cached_value(
					"Company", company, "default_payable_account"))
			results.append({
				"type":       "party",
				"value":      s.name,
				"label":      s.supplier_name + "  (Supplier)",
				"meta":       "Supplier  ·  " + (acc or ""),
				"party_type": "Supplier",
				"account":    acc or "",
			})

	# 4. Employees
	if len(results) < 35:
		employees = frappe.db.sql("""
			SELECT name, employee_name FROM `tabEmployee`
			WHERE status = 'Active'
			  AND (name LIKE %(like)s OR employee_name LIKE %(like)s)
			ORDER BY name LIMIT 5
		""", {"like": like}, as_dict=True)

		for emp in employees:
			acc = frappe.get_cached_value(
				"Company", company, "default_payable_account") or ""
			results.append({
				"type":       "party",
				"value":      emp.name,
				"label":      emp.employee_name + "  (Employee)",
				"meta":       "Employee  ·  " + acc,
				"party_type": "Employee",
				"account":    acc,
			})

	return results[:35]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _resolve_voucher(e):
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

	if vt == "Purchase Invoice":
		return "Purchase Invoice", vno, "/desk/purchase-invoice/" + vno

	if vt == "Sales Invoice":
		return "Sales Invoice", vno, "/desk/sales-invoice/" + vno

	slug = vt.lower().replace(" ", "-")
	return vt, vno, "/desk/" + slug + "/" + vno


def _clean_against(against_str):
	parts = [a.strip() for a in against_str.split(",") if a.strip()]
	if not parts:
		return ""
	if len(parts) == 1:
		return parts[0]
	return "Various"
