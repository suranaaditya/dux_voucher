import frappe
from frappe import _
from frappe.utils import flt, getdate, formatdate


# ══════════════════════════════════════════════════════════════════════
# LEDGER STATEMENT
# ══════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_ledger_statement(company, account, from_date, to_date,
						  party=None, party_type=None):
	"""
	Tally-style ledger statement with running balance.
	- party + party_type supplied  → filter by party field (specific Customer/Supplier/Employee)
	- only account supplied        → filter by account field
	"""
	if not all([company, account, from_date, to_date]):
		frappe.throw(_("Company, Account, From Date and To Date are all required"))

	from_date = getdate(from_date)
	to_date   = getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	use_party = bool(party and party_type)

	# ── Opening Balance ───────────────────────────────────────────────
	# Roll into opening: anything before the period, plus any entry within
	# the period flagged is_opening='Yes' (matches ERPNext General Ledger
	# behaviour with "Show Opening Entries" off).
	if use_party:
		ob_row = frappe.db.sql("""
			SELECT COALESCE(SUM(debit_in_account_currency),0)  AS total_debit,
			       COALESCE(SUM(credit_in_account_currency),0) AS total_credit
			FROM `tabGL Entry`
			WHERE party=%(party)s AND party_type=%(party_type)s
			  AND company=%(company)s AND is_cancelled=0
			  AND (
			        posting_date < %(from_date)s
			     OR (is_opening='Yes' AND posting_date BETWEEN %(from_date)s AND %(to_date)s)
			  )
		""", dict(party=party, party_type=party_type, company=company,
				  from_date=from_date, to_date=to_date), as_dict=True)
	else:
		ob_row = frappe.db.sql("""
			SELECT COALESCE(SUM(debit_in_account_currency),0)  AS total_debit,
			       COALESCE(SUM(credit_in_account_currency),0) AS total_credit
			FROM `tabGL Entry`
			WHERE account=%(account)s AND company=%(company)s AND is_cancelled=0
			  AND (
			        posting_date < %(from_date)s
			     OR (is_opening='Yes' AND posting_date BETWEEN %(from_date)s AND %(to_date)s)
			  )
		""", dict(account=account, company=company,
				  from_date=from_date, to_date=to_date), as_dict=True)

	ob_net = flt(ob_row[0].total_debit) - flt(ob_row[0].total_credit) if ob_row else 0.0

	# ── Period GL Entries ─────────────────────────────────────────────
	# Exclude is_opening='Yes' entries — they're already absorbed above.
	if use_party:
		where  = "gle.party=%(party)s AND gle.party_type=%(party_type)s AND gle.company=%(company)s AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s AND gle.is_opening='No' AND gle.is_cancelled=0"
		params = dict(party=party, party_type=party_type, company=company,
					  from_date=from_date, to_date=to_date)
	else:
		where  = "gle.account=%(account)s AND gle.company=%(company)s AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s AND gle.is_opening='No' AND gle.is_cancelled=0"
		params = dict(account=account, company=company,
					  from_date=from_date, to_date=to_date)

	entries = frappe.db.sql("""
		SELECT
			gle.posting_date, gle.account, gle.voucher_type, gle.voucher_no,
			gle.against, gle.debit_in_account_currency AS debit,
			gle.credit_in_account_currency AS credit,
			gle.remarks, gle.party_type, gle.party, gle.creation,
			CASE WHEN gle.voucher_type='Payment Entry' THEN pe.custom_source_voucher_doctype
			     WHEN gle.voucher_type='Journal Entry'  THEN je.custom_source_voucher_doctype
			     ELSE NULL END AS source_doctype,
			CASE WHEN gle.voucher_type='Payment Entry' THEN pe.custom_source_voucher
			     WHEN gle.voucher_type='Journal Entry'  THEN je.custom_source_voucher
			     ELSE NULL END AS source_voucher,
			CASE WHEN gle.voucher_type='Payment Entry' THEN pe.payment_type ELSE NULL END AS payment_type
		FROM `tabGL Entry` gle
		LEFT JOIN `tabPayment Entry` pe ON pe.name=gle.voucher_no AND gle.voucher_type='Payment Entry'
		LEFT JOIN `tabJournal Entry`  je ON je.name=gle.voucher_no AND gle.voucher_type='Journal Entry'
		WHERE {where}
		ORDER BY gle.posting_date, gle.creation
	""".format(where=where), params, as_dict=True)

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
		prefix  = "To" if dr > 0 else "By"
		contra  = e.account if use_party else (e.party or _clean_against(e.against or ""))

		rows.append(dict(
			posting_date  = formatdate(e.posting_date, "dd-MMM-yy"),
			prefix        = prefix,
			contra        = contra,
			voucher_type  = display_type,
			voucher_no    = display_vch,
			voucher_url   = vch_url,
			debit         = dr,
			credit        = cr,
			balance       = abs(running),
			balance_type  = "Dr" if running >= 0 else "Cr",
			remarks       = (e.remarks or "").strip(),
		))

	closing = running
	if use_party:
		display_name = party
		acc_type     = party_type
	else:
		meta = frappe.db.get_value("Account", account,
			["account_name","account_type"], as_dict=True) or {}
		display_name = meta.get("account_name", account)
		acc_type     = meta.get("account_type", "")

	return dict(
		company         = company,
		account         = account,
		account_name    = display_name,
		account_type    = acc_type,
		from_date       = formatdate(from_date, "dd-MMM-yyyy"),
		to_date         = formatdate(to_date,   "dd-MMM-yyyy"),
		opening_balance = abs(ob_net),
		opening_type    = "Dr" if ob_net >= 0 else "Cr",
		closing_balance = abs(closing),
		closing_type    = "Dr" if closing >= 0 else "Cr",
		total_debit     = total_dr,
		total_credit    = total_cr,
		rows            = rows,
		row_count       = len(rows),
	)


@frappe.whitelist()
def search_ledger(company, search_txt=""):
	"""
	Search accounts + Customer/Supplier/Employee parties.
	Returns {type, value, label, meta, party_type, account} per item.
	"""
	if not company:
		return []
	like = "%" + (search_txt or "") + "%"
	results = []

	# 1. Account master
	for a in frappe.db.sql("""
		SELECT name, account_name, account_type FROM `tabAccount`
		WHERE company=%(co)s AND is_group=0 AND disabled=0
		  AND (name LIKE %(l)s OR account_name LIKE %(l)s)
		ORDER BY name LIMIT 15
	""", dict(co=company, l=like), as_dict=True):
		results.append(dict(type="account", value=a.name,
			label=a.account_name,
			meta=(a.account_type or "Account") + "  ·  " + a.name,
			party_type=None, account=a.name))

	# 2. Customers
	if len(results) < 25:
		for c in frappe.db.sql("""
			SELECT name, customer_name FROM `tabCustomer`
			WHERE disabled=0 AND (name LIKE %(l)s OR customer_name LIKE %(l)s)
			ORDER BY name LIMIT 8
		""", dict(l=like), as_dict=True):
			acc = (frappe.db.get_value("Party Account",
					{"parent":c.name,"company":company,"parenttype":"Customer"},"account")
				   or frappe.get_cached_value("Company",company,"default_receivable_account") or "")
			if acc:
				results.append(dict(type="party", value=c.name,
					label=c.customer_name + "  (Customer)",
					meta="Customer  ·  " + acc,
					party_type="Customer", account=acc))

	# 3. Suppliers
	if len(results) < 30:
		for s in frappe.db.sql("""
			SELECT name, supplier_name FROM `tabSupplier`
			WHERE disabled=0 AND (name LIKE %(l)s OR supplier_name LIKE %(l)s)
			ORDER BY name LIMIT 8
		""", dict(l=like), as_dict=True):
			acc = (frappe.db.get_value("Party Account",
					{"parent":s.name,"company":company,"parenttype":"Supplier"},"account")
				   or frappe.get_cached_value("Company",company,"default_payable_account") or "")
			if acc:
				results.append(dict(type="party", value=s.name,
					label=s.supplier_name + "  (Supplier)",
					meta="Supplier  ·  " + acc,
					party_type="Supplier", account=acc))

	# 4. Employees
	if len(results) < 35:
		for emp in frappe.db.sql("""
			SELECT name, employee_name FROM `tabEmployee`
			WHERE status='Active' AND (name LIKE %(l)s OR employee_name LIKE %(l)s)
			ORDER BY name LIMIT 5
		""", dict(l=like), as_dict=True):
			acc = frappe.get_cached_value("Company",company,"default_payable_account") or ""
			results.append(dict(type="party", value=emp.name,
				label=emp.employee_name + "  (Employee)",
				meta="Employee  ·  " + acc,
				party_type="Employee", account=acc))

	return results[:35]


# ══════════════════════════════════════════════════════════════════════
# DAY BOOK
# ══════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_day_book(company, from_date, to_date, voucher_type_filter=None):
	"""
	Day Book — one row per voucher ordered by date + creation time.
	Returns: vouchers with resolved display type, party particulars, amount.
	voucher_type_filter: All / Payment Voucher / Receipt Voucher /
	                     Contra Entry / Journal Entry / Purchase Invoice / Sales Invoice
	"""
	if not all([company, from_date, to_date]):
		frappe.throw(_("Company, From Date and To Date are required"))

	from_date = getdate(from_date)
	to_date   = getdate(to_date)
	if from_date > to_date:
		frappe.throw(_("From Date cannot be after To Date"))

	# One row per voucher — GROUP BY voucher_no
	rows_raw = frappe.db.sql("""
		SELECT
			gle.posting_date,
			gle.voucher_type,
			gle.voucher_no,
			SUM(gle.debit_in_account_currency)  AS total_debit,
			SUM(gle.credit_in_account_currency) AS total_credit,
			GROUP_CONCAT(DISTINCT NULLIF(gle.party,'')
				ORDER BY gle.party SEPARATOR '  ·  ') AS parties,
			MAX(gle.remarks)  AS remarks,
			MIN(gle.creation) AS creation,
			MAX(CASE WHEN gle.voucher_type='Payment Entry'
					THEN pe.custom_source_voucher_doctype ELSE
				CASE WHEN gle.voucher_type='Journal Entry'
					THEN je.custom_source_voucher_doctype ELSE NULL END
			END) AS source_doctype,
			MAX(CASE WHEN gle.voucher_type='Payment Entry'
					THEN pe.custom_source_voucher ELSE
				CASE WHEN gle.voucher_type='Journal Entry'
					THEN je.custom_source_voucher ELSE NULL END
			END) AS source_voucher,
			MAX(CASE WHEN gle.voucher_type='Payment Entry'
					THEN pe.payment_type ELSE NULL END) AS payment_type
		FROM `tabGL Entry` gle
		LEFT JOIN `tabPayment Entry` pe
			ON pe.name=gle.voucher_no AND gle.voucher_type='Payment Entry'
		LEFT JOIN `tabJournal Entry`  je
			ON je.name=gle.voucher_no AND gle.voucher_type='Journal Entry'
		WHERE gle.company=%(company)s
		  AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s
		  AND gle.is_cancelled=0
		GROUP BY gle.posting_date, gle.voucher_type, gle.voucher_no
		ORDER BY gle.posting_date, MIN(gle.creation)
	""", dict(company=company, from_date=from_date, to_date=to_date), as_dict=True)

	rows   = []
	totals = dict(debit=0.0, credit=0.0, count=0)

	for e in rows_raw:
		display_type, display_vch, vch_url = _resolve_voucher(e)

		# Apply voucher type filter (Python level — simple and fast)
		if voucher_type_filter and voucher_type_filter != "All":
			if display_type != voucher_type_filter:
				continue

		dr  = flt(e.total_debit)
		cr  = flt(e.total_credit)
		amt = dr  # debit = credit in balanced entry; show debit side as amount

		# Particulars: prefer party names, fall back to "Various"
		parties = (e.parties or "").strip()
		if parties:
			particulars = parties
		else:
			particulars = "Various"

		totals["debit"]  += dr
		totals["credit"] += cr
		totals["count"]  += 1

		rows.append(dict(
			posting_date  = formatdate(e.posting_date, "dd-MMM-yy"),
			voucher_type  = display_type,
			voucher_no    = display_vch,
			voucher_url   = vch_url,
			particulars   = particulars,
			amount        = amt,
			remarks       = (e.remarks or "").strip(),
		))

	return dict(
		company   = company,
		from_date = formatdate(from_date, "dd-MMM-yyyy"),
		to_date   = formatdate(to_date,   "dd-MMM-yyyy"),
		rows      = rows,
		row_count = totals["count"],
		total_debit  = totals["debit"],
		total_credit = totals["credit"],
	)


# ══════════════════════════════════════════════════════════════════════
# CASH & BANK BOOK  (data comes from get_ledger_statement)
# ══════════════════════════════════════════════════════════════════════

@frappe.whitelist()
def get_bank_cash_accounts(company):
	"""
	Return all Bank and Cash type accounts for a company.
	Used to populate the Cash/Bank Book account picker.
	"""
	if not company:
		return []
	return frappe.db.sql("""
		SELECT name, account_name, account_type
		FROM `tabAccount`
		WHERE company=%(company)s
		  AND account_type IN ('Bank','Cash')
		  AND is_group=0
		  AND disabled=0
		ORDER BY account_type, account_name
	""", dict(company=company), as_dict=True)


# ══════════════════════════════════════════════════════════════════════
# SHARED HELPERS
# ══════════════════════════════════════════════════════════════════════

def _resolve_voucher(e):
	"""
	Map a GL Entry (or Day Book row) to:
	  display_type  — user-facing label
	  display_vch   — voucher number shown (Dux Voucher if available)
	  vch_url       — desk link
	"""
	src_dt  = (e.get("source_doctype") or "").strip()
	src_vch = (e.get("source_voucher")  or "").strip()
	pmt     = (e.get("payment_type")    or "").strip()
	vt      = e.voucher_type
	vno     = e.voucher_no

	# ── Dux Voucher origins ──────────────────────────────────────────
	if src_dt == "Payment Voucher" and src_vch:
		label = "Contra Entry" if pmt == "Internal Transfer" else "Payment Voucher"
		return label, src_vch, "/desk/payment-voucher/" + src_vch

	if src_dt == "Receipt Voucher" and src_vch:
		return "Receipt Voucher", src_vch, "/desk/receipt-voucher/" + src_vch

	# ── Native ERPNext vouchers ──────────────────────────────────────
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
	if not parts:    return ""
	if len(parts) == 1: return parts[0]
	return "Various"


@frappe.whitelist()
def get_permitted_companies():
    """
    Return list of companies the current user has access to.
    Uses User Permission if set, else returns all non-group companies.
    Runs server-side so no direct User Permission doctype access needed.
    """
    user = frappe.session.user
    user_perms = frappe.db.get_all(
        'User Permission',
        filters={'user': user, 'allow': 'Company'},
        fields=['for_value'],
        limit=200
    )
    if user_perms:
        return [p.for_value for p in user_perms]
    # No user permissions set — return all non-group companies
    companies = frappe.db.get_all(
        'Company',
        filters={'is_group': 0},
        fields=['name'],
        order_by='name asc',
        limit=200
    )
    return [c.name for c in companies]
