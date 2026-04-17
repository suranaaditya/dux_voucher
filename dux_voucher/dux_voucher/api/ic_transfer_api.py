import frappe
from frappe import _


@frappe.whitelist()
def get_all_companies(doctype, txt, searchfield, start, page_len, filters):
	"""
	Return all non-group companies for the 'other company' selector.

	Deliberately ignores User Permissions — user needs to be able to
	address a transfer to any company even if they don't have access to it.
	They are only selecting the company NAME, not accessing its data.
	"""
	import json

	if isinstance(filters, str):
		filters = json.loads(filters)

	exclude = (filters or {}).get("exclude_company", "")
	like = "%" + (txt or "") + "%"

	conditions = "is_group = 0 AND (name LIKE %(like)s OR abbr LIKE %(like)s)"
	params = {"like": like, "start": int(start), "page_len": int(page_len)}

	if exclude:
		conditions += " AND name != %(exclude)s"
		params["exclude"] = exclude

	return frappe.db.sql("""
		SELECT name, abbr
		FROM `tabCompany`
		WHERE {conditions}
		ORDER BY name
		LIMIT %(start)s, %(page_len)s
	""".format(conditions=conditions), params)


@frappe.whitelist()
def user_has_company_permission(company):
	"""
	Returns True if the current user has User Permission for the given company,
	or if they are a System Manager.
	Used by JS to decide whether to show the Confirm button.
	"""
	user = frappe.session.user
	roles = frappe.get_roles(user)

	if "System Manager" in roles:
		return True

	result = frappe.db.get_all(
		"User Permission",
		filters={"user": user, "allow": "Company", "for_value": company},
		fields=["name"],
		limit=1,
	)
	return bool(result)


@frappe.whitelist()
def get_pending_ic_entries_count(companies):
	"""
	Returns count of ICT entries where mirror is Pending Review
	and the other company is in the provided list.

	Called from dux_portal api.py to populate the notification badge.
	"""
	import json

	if isinstance(companies, str):
		companies = json.loads(companies)

	if not companies:
		return 0

	result = frappe.db.sql("""
		SELECT COUNT(*) AS cnt
		FROM `tabInter-Company Transfer`
		WHERE docstatus = 1
		  AND mirror_status = 'Pending Review'
		  AND (
		      paid_to_company IN %(companies)s
		      OR received_from_company IN %(companies)s
		  )
	""", {"companies": companies}, as_dict=True)

	return result[0].cnt if result else 0


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_user_companies(doctype, txt, searchfield, start, page_len, filters):
	user = frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return frappe.get_all("Company",
			filters={"is_group": 0, "name": ("like", f"%{txt}%")},
			fields=["name"],
			as_list=True)
	perms = frappe.get_all("User Permission",
		filters={"user": user, "allow": "Company"},
		fields=["for_value"])
	allowed = [p.for_value for p in perms]
	if not allowed:
		return []
	return frappe.get_all("Company",
		filters={"is_group": 0, "name": ("in", allowed)},
		fields=["name"],
		as_list=True)


def get_ict_permission_query(user):
	if not user:
		user = frappe.session.user
	if "System Manager" in frappe.get_roles(user):
		return ""
	perms = frappe.get_all("User Permission",
		filters={"user": user, "allow": "Company"},
		fields=["for_value"])
	if not perms:
		return "1=0"
	companies = ", ".join([frappe.db.escape(p.for_value) for p in perms])
	return (
		f"`tabInter-Company Transfer`.`company` IN ({companies})"
		f" OR `tabInter-Company Transfer`.`paid_to_company` IN ({companies})"
		f" OR `tabInter-Company Transfer`.`received_from_company` IN ({companies})"
	)


def ict_has_permission(doc, ptype, user):
	if ptype not in ("read", "write", "create", "submit", "cancel", "print", "email", "share"):
		return None
	if "System Manager" in frappe.get_roles(user):
		return True
	perms = frappe.get_all("User Permission",
		filters={"user": user, "allow": "Company"},
		fields=["for_value"],
		limit=100)
	allowed = {p.for_value for p in perms}
	if not allowed:
		return False
	return (
		doc.company in allowed
		or (doc.paid_to_company and doc.paid_to_company in allowed)
		or (doc.received_from_company and doc.received_from_company in allowed)
	)


@frappe.whitelist()
def can_user_confirm(docname):
	doc = frappe.get_doc('Inter-Company Transfer', docname)
	if doc.docstatus != 1 or doc.mirror_status != 'Pending Review':
		return None
	other_company = doc.paid_to_company if doc.transfer_type == 'Payment' else doc.received_from_company
	if not other_company:
		return None
	roles = frappe.get_roles()
	if 'System Manager' in roles:
		return {'other_company': other_company}
	perms = frappe.get_all('User Permission',
		filters={'user': frappe.session.user, 'allow': 'Company', 'for_value': other_company},
		limit=1)
	return {'other_company': other_company} if perms else None


@frappe.whitelist()
def validate_mapping_rows(rows):
	"""
	Validates CSV rows before inserting into IC Company Account Mapping child table.
	Checks company exists and account_label exists under Branch / Divisions in at least one company.
	Returns { valid: [...], invalid: [...] }
	"""
	import json

	if isinstance(rows, str):
		rows = json.loads(rows)

	# Get the branch group name from settings (configurable per deployment)
	branch_group_label = frappe.db.get_single_value(
		"Inter-Company Transfer Settings", "branch_group_name"
	) or "Branch / Divisions"

	valid = []
	invalid = []

	for row in rows:
		company = (row.get("company") or "").strip()
		account_label = (row.get("account_label") or "").strip()

		if not company or not account_label:
			invalid.append({"company": company or "(empty)", "reason": "Company or account label is blank"})
			continue

		# Check company exists
		if not frappe.db.exists("Company", company):
			invalid.append({"company": company, "reason": "Company not found in ERPNext"})
			continue

		# Check account_label exists under Branch / Divisions in at least one company's COA
		exists = frappe.db.sql("""
			SELECT a.name FROM `tabAccount` a
			INNER JOIN `tabAccount` parent ON parent.name = a.parent_account
			WHERE a.account_name = %s
			  AND parent.account_name = %s
			  AND a.is_group = 0
			LIMIT 1
		""", (account_label, branch_group_label), as_dict=True)

		if not exists:
			invalid.append({
				"company": company,
				"reason": (
					f"Account label '{account_label}' not found under "
					f"'{branch_group_label}' in any company's COA"
				)
			})
			continue

		valid.append({
			"company": company,
			"account_label": account_label,
		})

	return {"valid": valid, "invalid": invalid}
