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

	# Resolve account_type up-front: needed both for the row-rendering
	# convention (Cash & Bank Book inverts To/By per the RGI house rule,
	# plain non-bank accounts keep the textbook rule) and for the closing
	# display label further down.
	acc_meta = frappe.db.get_value(
		"Account", account, ["account_name", "account_type"], as_dict=True,
	) or {}
	acc_type = acc_meta.get("account_type", "") or ""
	# Inverted convention applies to:
	#   * the party ledger (already in this function via use_party=True)
	#   * any Cash or Bank account (i.e. the Cash & Bank Book page, and
	#     also anyone opening such an account via the Ledger Statement
	#     account picker — same account, same convention)
	# Plain non-bank accounts (Sales, Expense, Sundry Creditors viewed
	# as an account rather than a party, …) keep the textbook convention.
	invert_to_by = use_party or acc_type in ("Bank", "Cash")

	# ── Opening Balance ───────────────────────────────────────────────
	# Roll into opening: anything before the period, plus any entry within
	# the period flagged is_opening='Yes' (matches ERPNext General Ledger
	# behaviour with "Show Opening Entries" off).
	#
	# Also exclude GL rows whose parent Payment Entry / Journal Entry is
	# cancelled (docstatus=2). When a PE/JE is cancelled, ERPNext keeps
	# the original GL rows AND posts sign-flipped reversal rows dated the
	# cancel date — both with is_cancelled=0 — so filtering on is_cancelled
	# alone leaves the cancelled voucher visible (and double-counted via
	# the reversal). The parent-docstatus exclusion catches both.
	cancelled_filter = """
		AND CASE gle.voucher_type
		      WHEN 'Payment Entry' THEN COALESCE(pe.docstatus, 0)
		      WHEN 'Journal Entry' THEN COALESCE(je.docstatus, 0)
		      ELSE 0
		    END != 2
	"""
	ob_joins = """
		FROM `tabGL Entry` gle
		LEFT JOIN `tabPayment Entry` pe ON pe.name=gle.voucher_no AND gle.voucher_type='Payment Entry'
		LEFT JOIN `tabJournal Entry`  je ON je.name=gle.voucher_no AND gle.voucher_type='Journal Entry'
	"""
	if use_party:
		ob_row = frappe.db.sql("""
			SELECT COALESCE(SUM(gle.debit_in_account_currency),0)  AS total_debit,
			       COALESCE(SUM(gle.credit_in_account_currency),0) AS total_credit
			{joins}
			WHERE gle.party=%(party)s AND gle.party_type=%(party_type)s
			  AND gle.company=%(company)s AND gle.is_cancelled=0
			  AND (
			        gle.posting_date < %(from_date)s
			     OR (gle.is_opening='Yes' AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s)
			  )
			{cancelled}
		""".format(joins=ob_joins, cancelled=cancelled_filter),
		dict(party=party, party_type=party_type, company=company,
			 from_date=from_date, to_date=to_date), as_dict=True)
	else:
		ob_row = frappe.db.sql("""
			SELECT COALESCE(SUM(gle.debit_in_account_currency),0)  AS total_debit,
			       COALESCE(SUM(gle.credit_in_account_currency),0) AS total_credit
			{joins}
			WHERE gle.account=%(account)s AND gle.company=%(company)s AND gle.is_cancelled=0
			  AND (
			        gle.posting_date < %(from_date)s
			     OR (gle.is_opening='Yes' AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s)
			  )
			{cancelled}
		""".format(joins=ob_joins, cancelled=cancelled_filter),
		dict(account=account, company=company,
			 from_date=from_date, to_date=to_date), as_dict=True)

	ob_net = flt(ob_row[0].total_debit) - flt(ob_row[0].total_credit) if ob_row else 0.0

	# ── Period GL Entries ─────────────────────────────────────────────
	# Exclude is_opening='Yes' entries — they're already absorbed above.
	# Exclude rows whose parent PE/JE has docstatus=2 (see opening-balance
	# comment above).
	if use_party:
		where  = ("gle.party=%(party)s AND gle.party_type=%(party_type)s AND gle.company=%(company)s "
		          "AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s "
		          "AND gle.is_opening='No' AND gle.is_cancelled=0" + cancelled_filter)
		params = dict(party=party, party_type=party_type, company=company,
					  from_date=from_date, to_date=to_date)
	else:
		where  = ("gle.account=%(account)s AND gle.company=%(company)s "
		          "AND gle.posting_date BETWEEN %(from_date)s AND %(to_date)s "
		          "AND gle.is_opening='No' AND gle.is_cancelled=0" + cancelled_filter)
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
		if use_party:
			# Party ledger — RGI house convention (inverse of textbook):
			# party debited (payment) -> "By", party credited (receipt) -> "To"
			prefix = "By" if dr > 0 else "To"
			contra = _clean_against(e.against or "") or e.account
		elif invert_to_by:
			# Cash & Bank Book — RGI house convention (same inversion as
			# party ledger). Bank Dr (receipt) reads as "By <source>",
			# Bank Cr (payment) reads as "To <destination>".
			prefix = "By" if dr > 0 else "To"
			contra = e.party or _clean_against(e.against or "")
		else:
			# Plain non-bank account view — standard textbook convention.
			prefix = "To" if dr > 0 else "By"
			contra = e.party or _clean_against(e.against or "")

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
		# Party ledger: surface the party type as the "account type"
		# label so the front-end renders the right badge.
		acc_type     = party_type
	else:
		display_name = acc_meta.get("account_name", account)
		# acc_type already fetched up-front (used by invert_to_by); reuse.

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
def search_ledger(company, search_txt="", parties_only=0):
	"""
	Search accounts + Customer/Supplier/Employee parties.
	Returns {type, value, label, meta, party_type, account} per item.

	parties_only=1  → skip the Account branch entirely. Used by the
	Party Ledger page where account-head selection is intentionally
	hidden (purchase-team-facing view).
	"""
	if not company:
		return []
	# Frappe passes whitelisted args through as strings; coerce.
	parties_only = bool(int(parties_only)) if parties_only else False
	like = "%" + (search_txt or "") + "%"
	results = []

	# 1. Account master — skipped when caller asked for parties only.
	if not parties_only:
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

	# ── Enrich rows that have no party with a more meaningful label.
	# "Various" is uninformative when the operator is scanning the day
	# book — for Stock Entries it should read as the department, for
	# Purchase Receipts the supplier, for Head-wise PV/RV and standalone
	# JEs the first account head (with " & more" if the voucher has more
	# than one row). Everything is pre-fetched in batches keyed by
	# voucher_no so the loop below stays a constant number of queries.
	particulars_map = _build_day_book_particulars_map(rows_raw)

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

		# Particulars: prefer party names; otherwise the per-voucher-type
		# label we resolved above; else fall back to "Various".
		parties = (e.parties or "").strip()
		if parties:
			particulars = parties
		else:
			particulars = particulars_map.get(e.voucher_no) or "Various"

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
# DAY BOOK — particulars enrichment
# ══════════════════════════════════════════════════════════════════════

def _build_day_book_particulars_map(rows_raw):
	"""For Day Book vouchers that have no party on their GL entries,
	resolve a more meaningful label than the bare "Various" fallback.

	Returns a dict keyed by ``voucher_no``. Values come from per-voucher-
	type lookups, all batched into one query per category so the cost
	stays O(1) per Day Book load:

	  * Purchase Receipt → ``supplier_name``
	  * Stock Entry      → ``custom_department`` (falls back to
	                       ``stock_entry_type`` if the custom field
	                       isn't installed on this site)
	  * Payment Voucher  → first PV Account Row's account head, plus
	    (Head-wise mode)   " & more" if the PV has more than one row
	  * Receipt Voucher  → mirror of PV via rv_account_row
	  * Standalone JE    → first Journal Entry Account, plus " & more"
	                       if the JE has more than one row

	Rows whose voucher type doesn't match any of these (Sales Invoice,
	Contra Entry, etc.) are absent from the returned map — the caller
	will then fall back to "Various".
	"""
	out = {}

	# Group voucher names by the lookup we need to perform.
	pr_names = []   # Purchase Receipts
	se_names = []   # Stock Entries
	pv_names = []   # PV via Head-wise (no party on GL)
	rv_names = []   # RV via Head-wise (no party on GL)
	je_names = []   # standalone JEs (no PV/RV source)

	for r in rows_raw:
		# Only enrich rows that the main loop will treat as "Various".
		if (r.get("parties") or "").strip():
			continue

		vt = r.voucher_type
		src_dt = (r.get("source_doctype") or "").strip()
		src_vch = (r.get("source_voucher") or "").strip()

		if vt == "Purchase Receipt":
			pr_names.append(r.voucher_no)
		elif vt == "Stock Entry":
			se_names.append(r.voucher_no)
		elif src_dt == "Payment Voucher" and src_vch:
			# Head-wise PV — look up the friendly account heads on the
			# PV doc itself (not the JE accounts, which are the technical
			# posting accounts).
			pv_names.append((r.voucher_no, src_vch))
		elif src_dt == "Receipt Voucher" and src_vch:
			rv_names.append((r.voucher_no, src_vch))
		elif vt == "Journal Entry":
			# Any other Journal Entry — plain manual JE, Inter-Company
			# Transfer, Ex Student Receipt/Refund, Student Fee Receipt,
			# whatever module posted it. The first JE Account row is a
			# meaningful label in every case (Cash - DD / Ex-Students
			# Receivable - GHRCE / Admission/Registration Fee, etc.), so
			# fall through to that regardless of source_doctype.
			je_names.append(r.voucher_no)

	# ── Purchase Receipt → supplier_name ─────────────────────────────
	if pr_names:
		for r in frappe.db.sql(
			"""SELECT name, COALESCE(supplier_name, supplier) AS label
			   FROM `tabPurchase Receipt` WHERE name IN %(names)s""",
			{"names": tuple(pr_names)}, as_dict=True,
		):
			if r.label:
				out[r.name] = r.label

	# ── Stock Entry → custom_department (fallback: stock_entry_type) ─
	if se_names:
		has_custom_dept = frappe.db.has_column(
			"Stock Entry", "custom_department"
		)
		field = "custom_department" if has_custom_dept else "stock_entry_type"
		for r in frappe.db.sql(
			f"""SELECT name, COALESCE(`{field}`, stock_entry_type) AS label
			    FROM `tabStock Entry` WHERE name IN %(names)s""",
			{"names": tuple(se_names)}, as_dict=True,
		):
			if r.label:
				out[r.name] = r.label

	# ── PV (Head-wise) → first PV Account Row's account + " & more" ──
	# pv_names is [(voucher_no, pv_doc_name)]; we group rows of the
	# child table by the PV parent, then attribute each child's first
	# row back to the voucher_no the Day Book sees.
	pv_doc_to_vch = {p: v for v, p in pv_names}
	if pv_doc_to_vch:
		_resolve_head_row_label(
			out          = out,
			doc_to_vch   = pv_doc_to_vch,
			child_table  = "tabPV Account Row",
		)

	# ── RV (Head-wise) → mirror of PV ────────────────────────────────
	rv_doc_to_vch = {p: v for v, p in rv_names}
	if rv_doc_to_vch:
		_resolve_head_row_label(
			out          = out,
			doc_to_vch   = rv_doc_to_vch,
			child_table  = "tabRV Account Row",
		)

	# ── Standalone Journal Entry → first JE Account + " & more" ─────
	if je_names:
		_resolve_head_row_label(
			out          = out,
			doc_to_vch   = {n: n for n in je_names},
			child_table  = "tabJournal Entry Account",
		)

	return out


def _resolve_head_row_label(out, doc_to_vch, child_table):
	"""Shared body for PV / RV / JE head-row enrichment.

	Reads ``account`` and ``idx`` from ``child_table`` for every parent
	doc in ``doc_to_vch``, then sets ``out[voucher_no]`` to the first
	row's account, plus " & more" when the parent has more than one
	row. ``doc_to_vch`` maps the parent doc name to the Day Book
	voucher_no that should receive the label (they are usually the same
	for JE, and different for PV/RV where voucher_no is the backend JE).
	"""
	parents = tuple(doc_to_vch.keys())
	rows = frappe.db.sql(
		f"""SELECT parent, account, idx
		    FROM `{child_table}` WHERE parent IN %(parents)s
		    ORDER BY parent, idx""",
		{"parents": parents}, as_dict=True,
	)
	# Group consecutively by parent (already ordered by parent, idx)
	by_parent = {}
	for r in rows:
		by_parent.setdefault(r.parent, []).append(r.account)
	for parent, accounts in by_parent.items():
		if not accounts:
			continue
		first = accounts[0]
		label = first
		if len(accounts) > 1:
			label = f"{first} & more"
		vch = doc_to_vch.get(parent)
		if vch:
			out[vch] = label


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
