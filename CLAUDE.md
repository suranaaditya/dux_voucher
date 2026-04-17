# Dux Voucher — Claude Code Context

## Project Overview
A Tally-style simplified Payment and Receipt Voucher app for ERPNext v16.
Replaces complex Payment Entry / Journal Entry workflow with two simple vouchers.

- **App name:** dux_voucher
- **GitHub:** https://github.com/suranaaditya/dux_voucher
- **Active branches:** `version-1` (main), `feature/combined-entry-mode` (Party + Head Entry work)
- **Dev server:** frappe@187.127.132.58
- **Dev site:** erp.jewonline.in
- **Bench path:** /home/frappe/frappe-bench
- **App path:** /home/frappe/frappe-bench/apps/dux_voucher
- **ERPNext / Frappe:** v16

---

## App Structure
```
dux_voucher/
└── dux_voucher/
    ├── hooks.py
    ├── utils.py              — cascade cancel from PE/JE to parent voucher
    └── dux_voucher/
        ├── api/
        │   ├── utils.py      — shared helpers
        │   └── payment_voucher_api.py
        ├── doctype/
        │   ├── payment_voucher/
        │   │   ├── payment_voucher.py
        │   │   └── payment_voucher.js
        │   ├── receipt_voucher/
        │   │   ├── receipt_voucher.py
        │   │   └── receipt_voucher.js
        │   ├── pv_party_row/
        │   ├── pv_account_row/
        │   ├── pv_combined_row/        — NEW: party + head hybrid rows (PV)
        │   ├── pv_backend_reference/
        │   ├── rv_party_row/
        │   ├── rv_account_row/
        │   ├── rv_combined_row/        — NEW: party + head hybrid rows (RV)
        │   └── rv_backend_reference/
        └── fixtures/
            └── custom_field.json
```

---

## Entry Modes

### Payment Voucher
1. **Party-wise** — One Payment Entry (type=Pay) per party row
2. **Head-wise** — One Journal Entry (Bank/Cash type); auto-adds bank/cash credit row
3. **Contra Entry** — Payment Entry (type=Internal Transfer)
4. **Party + Head Entry** — One Journal Entry that can mix party rows (Customer/Supplier/Employee) and plain account heads in a single voucher; each party row auto-resolves to its default ledger (Sundry Creditors/Debtors/etc.); auto-adds bank/cash credit row for net difference

### Receipt Voucher
1. **Party-wise** — One Payment Entry (type=Receive) per party row
2. **Head-wise** — One Journal Entry; auto-adds bank/cash debit row
3. **Party + Head Entry** — Mirror of PV combined mode; credit-first auto-fill; auto-adds bank/cash debit row for net difference

---

## Key Business Logic
- Auto-detect party type (Customer/Supplier/Employee) from single search dialog
- Party search dialog with keyboard navigation (arrow keys + enter)
- Amount auto-sums from party rows
- Head-wise: first row auto-fills, next rows auto-balance
- **Party + Head Entry**: party selection auto-fills ledger account via `get_party_default_account()` API; if no party, account is picked manually; backend JE populates `party_type` + `party` on each row so ERPNext's native party validation works (Sundry Creditors for Supplier, Sundry Debtors for Customer, etc.)
- Cancel voucher → cancels all backend entries
- Cancel backend entry directly → cancels parent voucher
- custom_remarks = 1 on Payment Entry
- Reference No → UTR (Bank/UPI) or Cheque Number (Cheque)

---

## Pending Work
- [ ] Print formats for Payment Voucher and Receipt Voucher
- [ ] Production deployment on Frappe Cloud
- [ ] Test with real data at client site (jewonline.in)
- [ ] Merge `feature/combined-entry-mode` → `version-1` after client validation

## Recently Completed
- [x] **Party + Head Entry** mode — hybrid voucher mixing parties and account heads, posts to Journal Entry with native party mapping (branch: `feature/combined-entry-mode`)

---

## How to Deploy Changes
```bash
# On dev server — commit and push
cd /home/frappe/frappe-bench/apps/dux_voucher
git add .
git commit -m "Description"
git push origin version-1

# Pull and restart
cd /home/frappe/frappe-bench
bench --site erp.jewonline.in migrate
bench build --app dux_voucher
bench restart
```

---

# CURRENT SOURCE CODE (local copy from dev server)

_Last synced from `frappe@187.127.132.58:/home/frappe/frappe-bench/apps/dux_voucher/`_

---

## hooks.py

```python
app_name = "dux_voucher"
app_title = "Dux Voucher"
app_publisher = "Dux Digitech"
app_description = "Simple Tally-style Payment and Receipt Voucher"
app_email = "aditya.surana@thesvsgroup.org"
app_license = "mit"

required_apps = ["erpnext"]

# Custom fields on Payment Entry and Journal Entry
# Synced automatically on every bench migrate
fixtures = [
    {
        "dt": "Custom Field",
        "filters": [
            ["name", "in", [
                "Payment Entry-custom_source_voucher_doctype",
                "Payment Entry-custom_source_voucher",
                "Journal Entry-custom_source_voucher_doctype",
                "Journal Entry-custom_source_voucher",
                "Company-custom_dux_voucher_settings",
                "Company-custom_voucher_print_logo",
                "Company-custom_voucher_footer_note",
            ]]
        ]
    },
]
# Cancel cascade from backend entries to parent voucher
doc_events = {
    "Payment Entry": {
        "on_cancel": "dux_voucher.dux_voucher.utils.on_payment_entry_cancel"
    },
    "Journal Entry": {
        "on_cancel": "dux_voucher.dux_voucher.utils.on_journal_entry_cancel"
    }
}
# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "dux_voucher",
# 		"logo": "/assets/dux_voucher/logo.png",
# 		"title": "Dux Voucher",
# 		"route": "/dux_voucher",
# 		"has_permission": "dux_voucher.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/dux_voucher/css/dux_voucher.css"
# app_include_js = "/assets/dux_voucher/js/dux_voucher.js"

# include js, css files in header of web template
# web_include_css = "/assets/dux_voucher/css/dux_voucher.css"
# web_include_js = "/assets/dux_voucher/js/dux_voucher.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "dux_voucher/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "dux_voucher/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "dux_voucher.utils.jinja_methods",
# 	"filters": "dux_voucher.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "dux_voucher.install.before_install"
# after_install = "dux_voucher.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "dux_voucher.uninstall.before_uninstall"
# after_uninstall = "dux_voucher.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "dux_voucher.utils.before_app_install"
# after_app_install = "dux_voucher.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "dux_voucher.utils.before_app_uninstall"
# after_app_uninstall = "dux_voucher.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "dux_voucher.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"dux_voucher.tasks.all"
# 	],
# 	"daily": [
# 		"dux_voucher.tasks.daily"
# 	],
# 	"hourly": [
# 		"dux_voucher.tasks.hourly"
# 	],
# 	"weekly": [
# 		"dux_voucher.tasks.weekly"
# 	],
# 	"monthly": [
# 		"dux_voucher.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "dux_voucher.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "dux_voucher.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "dux_voucher.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "dux_voucher.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["dux_voucher.utils.before_request"]
# after_request = ["dux_voucher.utils.after_request"]

# Job Events
# ----------
# before_job = ["dux_voucher.utils.before_job"]
# after_job = ["dux_voucher.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"dux_voucher.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []
```

---

## utils.py

```python
404: Not Found
```

---

## dux_voucher/api/utils.py

```python
import frappe
from frappe import _
from frappe.utils import flt


def _detect_party_type(party_name):
    """Return Customer, Supplier, Employee or None."""
    for dt in ("Customer", "Supplier", "Employee"):
        if frappe.db.exists(dt, party_name):
            return dt
    return None


def _get_party_account(party_type, party, company):
    """Get the ledger account for a party in a company."""
    if party_type == "Customer":
        acc = frappe.db.get_value(
            "Party Account",
            {"parent": party, "company": company, "parenttype": "Customer"},
            "account"
        )
        return acc or frappe.get_cached_value(
            "Company", company, "default_receivable_account"
        )
    elif party_type == "Supplier":
        acc = frappe.db.get_value(
            "Party Account",
            {"parent": party, "company": company, "parenttype": "Supplier"},
            "account"
        )
        return acc or frappe.get_cached_value(
            "Company", company, "default_payable_account"
        )
    elif party_type == "Employee":
        return frappe.get_cached_value(
            "Company", company, "default_payable_account"
        )
    return None


def _get_account_currency(account, company):
    """Get currency of an account, fallback to company currency."""
    currency = frappe.db.get_value("Account", account, "account_currency")
    return (
        currency
        or frappe.get_cached_value("Company", company, "default_currency")
        or "INR"
    )


def _get_account_type(account):
    """Get account type from Account master."""
    return frappe.db.get_value("Account", account, "account_type") or ""


def _validate_bank_cash_account(account, label):
    """Throw if account is not Bank or Cash type."""
    account_type = _get_account_type(account)
    if account_type not in ("Bank", "Cash"):
        frappe.throw(
            _("{0} must be a Bank or Cash type account. "
              "'{1}' is of type '{2}'").format(label, account, account_type)
        )


def _submit_doc(doc):
    """
    Insert and submit a document.
    Shows exact ERPNext error to user if anything fails.
    """
    try:
        doc.flags.ignore_permissions = True
        doc.insert()
        doc.submit()
    except frappe.ValidationError:
        raise
    except Exception as e:
        frappe.throw(
            _("Error while creating {0}: {1}").format(doc.doctype, str(e))
        )


def _safe_cancel(doctype, docname):
    """
    Cancel a backend document safely.
    Skips if already cancelled or doesn't exist.
    """
    if not docname:
        return
    if not frappe.db.exists(doctype, docname):
        return
    docstatus = frappe.db.get_value(doctype, docname, "docstatus")
    if docstatus != 1:
        return
    try:
        doc = frappe.get_doc(doctype, docname)
        doc.flags.ignore_permissions = True
        doc.cancel()
    except Exception as e:
        frappe.throw(
            _("Error cancelling {0} {1}: {2}").format(doctype, docname, str(e))
        )


def get_mop_type(mode_of_payment):
    """Return Mode of Payment type — Bank or Cash."""
    if not mode_of_payment:
        return "Bank"
    return frappe.db.get_value(
        "Mode of Payment", mode_of_payment, "type"
    ) or "Bank"
```

---

## dux_voucher/api/payment_voucher_api.py

```python
import frappe
from frappe import _
from frappe.utils import flt, today
from dux_voucher.dux_voucher.api.utils import _detect_party_type


@frappe.whitelist()
def get_party_type(party_name):
    """Auto-detect if party is Customer, Supplier or Employee."""
    return _detect_party_type(party_name)


@frappe.whitelist()
def get_party_details(party_name):
    """
    Return party_type and display name for a given party name.
    Called from JS when user selects a party in the search dialog.
    """
    party_type = _detect_party_type(party_name)
    if not party_type:
        return None

    name_field_map = {
        "Customer": "customer_name",
        "Supplier": "supplier_name",
        "Employee": "employee_name"
    }
    name_field = name_field_map.get(party_type)
    display_name = frappe.db.get_value(
        party_type, party_name, name_field
    ) or ""

    return {
        "party_type": party_type,
        "party_name": display_name
    }


@frappe.whitelist()
def search_party(doctype, txt, searchfield, start, page_len, filters):
    """
    Search across Customer, Supplier and Employee in one query.
    Used as custom search for Party field in party rows table.
    Returns rows of (name, display_name, party_type).
    """
    txt = "%" + (txt or "") + "%"
    per_dt = max(1, int(page_len) // 3 + 1)
    results = []

    for dt, name_field, condition in (
        ("Customer", "customer_name", "disabled = 0"),
        ("Supplier", "supplier_name", "disabled = 0"),
        ("Employee", "employee_name", "status = 'Active'"),
    ):
        rows = frappe.db.sql(
            """
            SELECT name, `{nf}`, '{dt}' as party_type
            FROM `tab{dt}`
            WHERE (`{nf}` LIKE %(txt)s OR name LIKE %(txt)s)
            AND {cond}
            ORDER BY name
            LIMIT %(pl)s
            """.format(dt=dt, nf=name_field, cond=condition),
            {"txt": txt, "pl": per_dt},
        )
        results.extend(rows)

    return results[:int(page_len)]


@frappe.whitelist()
def get_mop_account_type(mode_of_payment):
    """
    Return account type (Bank/Cash) for a Mode of Payment.
    Used by JS to filter Paid From Account dropdown.
    """
    if not mode_of_payment:
        return None
    return frappe.db.get_value(
        "Mode of Payment", mode_of_payment, "type"
    )


@frappe.whitelist()
def validate_backend_entry(voucher_doctype, voucher_name):
    """
    Dry-run validation of backend entry before submitting.
    Returns any errors so JS can show them to user.
    """
    errors = []
    try:
        doc = frappe.get_doc(voucher_doctype, voucher_name)
        doc.run_method("validate")
    except frappe.ValidationError as e:
        errors.append(str(e))
    except Exception as e:
        errors.append(str(e))

    return {"errors": errors}


@frappe.whitelist()
def get_party_balance(party_type, party, company, posting_date=None):
    """
    Get current outstanding GL balance for a party (Customer/Supplier/Employee).
    Returns balance amount and Dr/Cr type.

    For Customers:  Dr balance = they owe us (outstanding receivable)
    For Suppliers:  Cr balance = we owe them (outstanding payable)
    For Employees:  Cr balance = salary/advance payable
    """
    posting_date = posting_date or today()

    result = frappe.db.sql(
        """
        SELECT
            SUM(debit_in_account_currency) - SUM(credit_in_account_currency) AS balance
        FROM `tabGL Entry`
        WHERE
            party_type = %s
            AND party = %s
            AND company = %s
            AND posting_date <= %s
            AND is_cancelled = 0
        """,
        (party_type, party, company, posting_date),
        as_dict=True,
    )

    raw = flt(result[0].balance) if result and result[0].balance is not None else 0

    if raw > 0.005:
        return {"balance": raw, "balance_type": "Dr"}
    elif raw < -0.005:
        return {"balance": abs(raw), "balance_type": "Cr"}
    else:
        return {"balance": 0, "balance_type": "Nil"}


@frappe.whitelist()
def get_account_balance(account, company, posting_date=None):
    """
    Get current GL balance for a ledger account.
    Returns balance amount and Dr/Cr type.
    """
    posting_date = posting_date or today()

    result = frappe.db.sql(
        """
        SELECT
            SUM(debit_in_account_currency) - SUM(credit_in_account_currency) AS balance
        FROM `tabGL Entry`
        WHERE
            account = %s
            AND company = %s
            AND posting_date <= %s
            AND is_cancelled = 0
        """,
        (account, company, posting_date),
        as_dict=True,
    )

    raw = flt(result[0].balance) if result and result[0].balance is not None else 0

    if raw > 0.005:
        return {"balance": raw, "balance_type": "Dr"}
    elif raw < -0.005:
        return {"balance": abs(raw), "balance_type": "Cr"}
    else:
        return {"balance": 0, "balance_type": "Nil"}

@frappe.whitelist()
def get_party_default_account(party_type, party, company):
    """Return the default ledger account for a party -- used by Combined mode auto-fill."""
    from dux_voucher.dux_voucher.api.utils import _get_party_account
    return _get_party_account(party_type, party, company)
```

---

## dux_voucher/doctype/payment_voucher/payment_voucher.py

```python
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dux_voucher.dux_voucher.api.utils import (
    _detect_party_type,
    _get_party_account,
    _get_account_currency,
    _validate_bank_cash_account,
    _submit_doc,
    _safe_cancel,
    get_mop_type,
)


class PaymentVoucher(Document):

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------
    def validate(self):
        self._validate_basics()
        if self.entry_mode == "Party-wise":
            self._validate_party_wise()
        elif self.entry_mode == "Head-wise":
            self._validate_head_wise()
        elif self.entry_mode == "Contra Entry":
            self._validate_contra()
        elif self.entry_mode == "Party + Head Entry":
            self._validate_combined()

    def _validate_basics(self):
        if not self.company:
            frappe.throw(_("Company is required"))
        if not self.posting_date:
            frappe.throw(_("Posting Date is required"))

    def _validate_party_wise(self):
        if not self.mode_of_payment:
            frappe.throw(_("Payment Method is required"))
        if not self.paid_from_account:
            frappe.throw(_("Paid From Account is required"))
        if not self.party_rows:
            frappe.throw(_("Please add at least one party row"))

        _validate_bank_cash_account(self.paid_from_account, "Paid From Account")

        row_total = sum(flt(r.amount) for r in self.party_rows)
        if not flt(self.amount):
            self.amount = row_total
        elif abs(flt(self.amount) - row_total) > 0.005:
            frappe.throw(
                _("Amount ({0}) must equal sum of party rows ({1})").format(
                    flt(self.amount), row_total
                )
            )

        for row in self.party_rows:
            if not row.party:
                frappe.throw(_("Row {0}: Party is required").format(row.idx))
            if not flt(row.amount) or flt(row.amount) <= 0:
                frappe.throw(
                    _("Row {0}: Amount must be greater than zero").format(row.idx)
                )
            if not row.party_type:
                row.party_type = _detect_party_type(row.party)
                if not row.party_type:
                    frappe.throw(
                        _("Row {0}: '{1}' not found as Customer, "
                          "Supplier or Employee").format(row.idx, row.party)
                    )
            if not frappe.db.exists(row.party_type, row.party):
                frappe.throw(
                    _("Row {0}: {1} '{2}' does not exist").format(
                        row.idx, row.party_type, row.party
                    )
                )

    def _validate_head_wise(self):
        if not self.mode_of_payment:
            frappe.throw(_("Payment Method is required"))
        if not self.paid_from_account:
            frappe.throw(_("Paid From Account is required"))
        if not self.account_rows:
            frappe.throw(_("Please add at least one account row"))

        _validate_bank_cash_account(self.paid_from_account, "Paid From Account")

        for row in self.account_rows:
            if not row.account:
                frappe.throw(_("Row {0}: Account is required").format(row.idx))
            if flt(row.debit) < 0 or flt(row.credit) < 0:
                frappe.throw(
                    _("Row {0}: Debit and Credit cannot be negative").format(row.idx)
                )
            if flt(row.debit) > 0 and flt(row.credit) > 0:
                frappe.throw(
                    _("Row {0}: A row cannot have both Debit and Credit").format(row.idx)
                )

        total_debit = sum(flt(r.debit) for r in self.account_rows)
        total_credit = sum(flt(r.credit) for r in self.account_rows)
        net_amount = total_debit - total_credit

        if net_amount <= 0:
            frappe.throw(
                _("Total Debit ({0}) must be greater than Total Credit ({1}). "
                  "The difference will be auto-credited to '{2}'").format(
                    total_debit, total_credit, self.paid_from_account
                )
            )

        self.amount = net_amount

    def _validate_contra(self):
        if not self.transfer_from_account:
            frappe.throw(_("Transfer From Account is required"))
        if not self.transfer_to_account:
            frappe.throw(_("Transfer To Account is required"))
        if self.transfer_from_account == self.transfer_to_account:
            frappe.throw(
                _("Transfer From and Transfer To accounts cannot be the same")
            )
        if not flt(self.amount) or flt(self.amount) <= 0:
            frappe.throw(_("Amount must be greater than zero"))

        _validate_bank_cash_account(self.transfer_from_account, "Transfer From Account")
        _validate_bank_cash_account(self.transfer_to_account, "Transfer To Account")

    # ------------------------------------------------------------------
    # On Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        refs = []
        try:
            if self.entry_mode == "Party-wise":
                refs = self._create_party_payment_entries()
            elif self.entry_mode == "Head-wise":
                refs = self._create_head_wise_journal_entry()
            elif self.entry_mode == "Contra Entry":
                refs = self._create_contra_payment_entry()
            elif self.entry_mode == "Party + Head Entry":
                refs = self._create_combined_journal_entry()
        except frappe.ValidationError:
            raise
        except Exception as e:
            frappe.db.rollback()
            frappe.throw(
                _("Error creating backend entries: {0}").format(str(e))
            )

        for ref in refs:
            row = frappe.new_doc("PV Backend Reference")
            row.parent = self.name
            row.parenttype = "Payment Voucher"
            row.parentfield = "backend_references"
            row.backend_doctype = ref["doctype"]
            row.backend_document = ref["name"]
            row.party = ref.get("party", "")
            row.amount = ref.get("amount", 0)
            row.insert(ignore_permissions=True)

        frappe.db.set_value("Payment Voucher", self.name, "is_posted", 1)

    # ------------------------------------------------------------------
    # On Cancel
    # ------------------------------------------------------------------
    def on_cancel(self):
        refs = frappe.get_all(
            "PV Backend Reference",
            filters={"parent": self.name},
            fields=["backend_doctype", "backend_document"]
        )
        for ref in refs:
            _safe_cancel(ref.backend_doctype, ref.backend_document)

        frappe.db.set_value("Payment Voucher", self.name, "is_posted", 0)

    # ------------------------------------------------------------------
    # Party-wise — one Payment Entry per row
    # ------------------------------------------------------------------
    def _create_party_payment_entries(self):
        refs = []
        for row in self.party_rows:
            party_account = _get_party_account(
                row.party_type, row.party, self.company
            )
            if not party_account:
                frappe.throw(
                    _("Could not find ledger account for {0} '{1}'. "
                      "Please set default payable/receivable account "
                      "in Company or Party master.").format(
                        row.party_type, row.party
                    )
                )

            pe = frappe.new_doc("Payment Entry")
            pe.payment_type = "Pay"
            pe.company = self.company
            pe.posting_date = self.posting_date
            pe.mode_of_payment = self.mode_of_payment
            pe.party_type = row.party_type
            pe.party = row.party
            pe.paid_from = self.paid_from_account
            pe.paid_to = party_account
            pe.paid_from_account_currency = _get_account_currency(
                self.paid_from_account, self.company
            )
            pe.paid_to_account_currency = _get_account_currency(
                party_account, self.company
            )
            pe.paid_amount = flt(row.amount)
            pe.received_amount = flt(row.amount)
            pe.source_exchange_rate = 1
            pe.target_exchange_rate = 1
            pe.reference_no = self.reference_no or ""
            pe.reference_date = self.reference_date or self.posting_date
            pe.custom_remarks = 1
            pe.remarks = self.remarks or ""
            pe.custom_source_voucher_doctype = "Payment Voucher"
            pe.custom_source_voucher = self.name

            _submit_doc(pe)
            refs.append({
                "doctype": "Payment Entry",
                "name": pe.name,
                "party": row.party,
                "amount": flt(row.amount)
            })
        return refs

    # ------------------------------------------------------------------
    # Head-wise — one Journal Entry with auto bank/cash credit row
    # ------------------------------------------------------------------
    def _create_head_wise_journal_entry(self):
        mop_type = get_mop_type(self.mode_of_payment)
        voucher_type = "Cash Entry" if mop_type == "Cash" else "Bank Entry"

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = voucher_type
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or ""
        je.cheque_date = self.reference_date or None
        je.user_remark = self.remarks or ""
        je.custom_source_voucher_doctype = "Payment Voucher"
        je.custom_source_voucher = self.name

        for row in self.account_rows:
            je.append("accounts", {
                "account": row.account,
                "debit_in_account_currency": flt(row.debit),
                "credit_in_account_currency": flt(row.credit),
                "cost_center": row.cost_center or self.cost_center or "",
                "project": row.project or self.project or "",
            })

        # Auto-add bank/cash credit row
        total_debit = sum(flt(r.debit) for r in self.account_rows)
        total_credit = sum(flt(r.credit) for r in self.account_rows)
        net_credit = total_debit - total_credit

        je.append("accounts", {
            "account": self.paid_from_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": net_credit,
            "cost_center": self.cost_center or "",
            "project": self.project or "",
        })

        _submit_doc(je)
        return [{
            "doctype": "Journal Entry",
            "name": je.name,
            "amount": net_credit
        }]

    # ------------------------------------------------------------------
    # Contra — Payment Entry Internal Transfer
    # ------------------------------------------------------------------
    def _create_contra_payment_entry(self):
        pe = frappe.new_doc("Payment Entry")
        pe.payment_type = "Internal Transfer"
        pe.company = self.company
        pe.posting_date = self.posting_date
        pe.mode_of_payment = self.mode_of_payment or ""
        pe.paid_from = self.transfer_from_account
        pe.paid_to = self.transfer_to_account
        pe.paid_from_account_currency = _get_account_currency(
            self.transfer_from_account, self.company
        )
        pe.paid_to_account_currency = _get_account_currency(
            self.transfer_to_account, self.company
        )
        pe.paid_amount = flt(self.amount)
        pe.received_amount = flt(self.amount)
        pe.source_exchange_rate = 1
        pe.target_exchange_rate = 1
        pe.reference_no = self.reference_no or ""
        pe.reference_date = self.reference_date or self.posting_date
        pe.custom_remarks = 1
        pe.remarks = self.remarks or ""
        pe.custom_source_voucher_doctype = "Payment Voucher"
        pe.custom_source_voucher = self.name

        _submit_doc(pe)
        return [{
            "doctype": "Payment Entry",
            "name": pe.name,
            "amount": flt(self.amount)
        }]

    # ------------------------------------------------------------------
    # Party + Head Entry -- validation
    # ------------------------------------------------------------------
    def _validate_combined(self):
        if not self.mode_of_payment:
            frappe.throw(_("Payment Method is required"))
        if not self.paid_from_account:
            frappe.throw(_("Paid From Account is required"))
        if not self.combined_rows:
            frappe.throw(_("Please add at least one row"))

        _validate_bank_cash_account(self.paid_from_account, "Paid From Account")

        for row in self.combined_rows:
            if not row.account:
                frappe.throw(_("Row {0}: Account is required").format(row.idx))
            if flt(row.debit) < 0 or flt(row.credit) < 0:
                frappe.throw(
                    _("Row {0}: Debit and Credit cannot be negative").format(row.idx)
                )
            if flt(row.debit) > 0 and flt(row.credit) > 0:
                frappe.throw(
                    _("Row {0}: A row cannot have both Debit and Credit").format(row.idx)
                )
            # If party is set, validate it exists
            if row.party:
                if not row.party_type:
                    row.party_type = _detect_party_type(row.party)
                    if not row.party_type:
                        frappe.throw(
                            _("Row {0}: '{1}' not found as Customer, "
                              "Supplier or Employee").format(row.idx, row.party)
                        )
                if not frappe.db.exists(row.party_type, row.party):
                    frappe.throw(
                        _("Row {0}: {1} '{2}' does not exist").format(
                            row.idx, row.party_type, row.party
                        )
                    )

        total_debit = sum(flt(r.debit) for r in self.combined_rows)
        total_credit = sum(flt(r.credit) for r in self.combined_rows)
        net_amount = total_debit - total_credit

        if net_amount <= 0:
            frappe.throw(
                _("Total Debit ({0}) must be greater than Total Credit ({1}). "
                  "The difference will be auto-credited to '{2}'").format(
                    total_debit, total_credit, self.paid_from_account
                )
            )

        self.amount = net_amount

    # ------------------------------------------------------------------
    # Party + Head Entry -- one Journal Entry with party mapping
    # ------------------------------------------------------------------
    def _create_combined_journal_entry(self):
        mop_type = get_mop_type(self.mode_of_payment)
        voucher_type = "Cash Entry" if mop_type == "Cash" else "Bank Entry"

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = voucher_type
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or ""
        je.cheque_date = self.reference_date or None
        je.user_remark = self.remarks or ""
        je.custom_source_voucher_doctype = "Payment Voucher"
        je.custom_source_voucher = self.name

        for row in self.combined_rows:
            je.append("accounts", {
                "account": row.account,
                "party_type": row.party_type or "",
                "party": row.party or "",
                "debit_in_account_currency": flt(row.debit),
                "credit_in_account_currency": flt(row.credit),
                "cost_center": row.cost_center or self.cost_center or "",
                "project": row.project or self.project or "",
            })

        # Auto-add bank/cash credit row
        total_debit = sum(flt(r.debit) for r in self.combined_rows)
        total_credit = sum(flt(r.credit) for r in self.combined_rows)
        net_credit = total_debit - total_credit

        je.append("accounts", {
            "account": self.paid_from_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": net_credit,
            "cost_center": self.cost_center or "",
            "project": self.project or "",
        })

        _submit_doc(je)
        return [{
            "doctype": "Journal Entry",
            "name": je.name,
            "amount": net_credit
        }]
```

---

## dux_voucher/doctype/payment_voucher/payment_voucher.json

```json
{
 "actions": [],
 "allow_rename": 1,
 "autoname": "naming_series:",
 "creation": "2026-03-29 07:47:31.237869",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": [
  "naming_series",
  "basic_details_section",
  "company",
  "mode_of_payment",
  "entry_mode",
  "basic_col_break",
  "posting_date",
  "paid_from_account",
  "amount",
  "party_wise_section",
  "party_rows",
  "head_wise_section",
  "account_rows",
  "combined_section",
  "combined_rows",
  "contra_section",
  "transfer_from_account",
  "contra_col_break",
  "transfer_to_account",
  "reference_section",
  "reference_no",
  "cost_center",
  "reference_col_break",
  "reference_date",
  "project",
  "remarks_section",
  "remarks",
  "backend_tracking_section",
  "is_posted",
  "backend_references_section",
  "backend_references",
  "amended_from"
 ],
 "fields": [
  {
   "fieldname": "naming_series",
   "fieldtype": "Select",
   "label": "Naming Series",
   "no_copy": 1,
   "options": "PV-.YYYY.-",
   "set_only_once": 1
  },
  {
   "fieldname": "basic_details_section",
   "fieldtype": "Section Break",
   "label": "Basic Details"
  },
  {
   "bold": 1,
   "fieldname": "company",
   "fieldtype": "Link",
   "in_list_view": 1,
   "label": "Company",
   "options": "Company",
   "reqd": 1
  },
  {
   "fieldname": "mode_of_payment",
   "fieldtype": "Link",
   "label": "Payment Method",
   "options": "Mode of Payment"
  },
  {
   "default": "Party-wise",
   "fieldname": "entry_mode",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Entry Mode",
   "options": "Party-wise\nHead-wise\nContra Entry\nParty + Head Entry",
   "reqd": 1
  },
  {
   "fieldname": "basic_col_break",
   "fieldtype": "Column Break"
  },
  {
   "default": "Today",
   "fieldname": "posting_date",
   "fieldtype": "Date",
   "in_list_view": 1,
   "label": "Posting Date",
   "reqd": 1
  },
  {
   "depends_on": "eval:doc.entry_mode !== 'Contra Entry'",
   "fieldname": "paid_from_account",
   "fieldtype": "Link",
   "label": "Paid From Account",
   "options": "Account"
  },
  {
   "fieldname": "amount",
   "fieldtype": "Currency",
   "label": "Amount"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party-wise'",
   "fieldname": "party_wise_section",
   "fieldtype": "Section Break",
   "label": "Party-wise Entries"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party-wise'",
   "fieldname": "party_rows",
   "fieldtype": "Table",
   "label": "Party Rows",
   "options": "PV Party Row"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Head-wise'",
   "fieldname": "head_wise_section",
   "fieldtype": "Section Break",
   "label": "Head-wise Entries"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Head-wise'",
   "fieldname": "account_rows",
   "fieldtype": "Table",
   "label": "Account Rows",
   "options": "PV Account Row"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Contra Entry'",
   "fieldname": "contra_section",
   "fieldtype": "Section Break",
   "label": "Contra Details"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Contra Entry'",
   "fieldname": "transfer_from_account",
   "fieldtype": "Link",
   "label": "Transfer From Account",
   "options": "Account"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Contra Entry'",
   "fieldname": "contra_col_break",
   "fieldtype": "Column Break"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Contra Entry'",
   "fieldname": "transfer_to_account",
   "fieldtype": "Link",
   "label": "Transfer To Account",
   "options": "Account"
  },
  {
   "fieldname": "reference_section",
   "fieldtype": "Section Break",
   "label": "Reference / Allocation Details"
  },
  {
   "fieldname": "reference_no",
   "fieldtype": "Data",
   "label": "Reference No"
  },
  {
   "fieldname": "cost_center",
   "fieldtype": "Link",
   "label": "Cost Center",
   "options": "Cost Center"
  },
  {
   "fieldname": "reference_col_break",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "reference_date",
   "fieldtype": "Date",
   "label": "Reference Date"
  },
  {
   "fieldname": "project",
   "fieldtype": "Link",
   "label": "Project",
   "options": "Project"
  },
  {
   "fieldname": "remarks_section",
   "fieldtype": "Section Break",
   "label": "Remarks"
  },
  {
   "fieldname": "remarks",
   "fieldtype": "Text",
   "label": "Remarks"
  },
  {
   "fieldname": "backend_tracking_section",
   "fieldtype": "Section Break",
   "label": "Backend Tracking"
  },
  {
   "default": "0",
   "fieldname": "is_posted",
   "fieldtype": "Check",
   "label": "Is Posted",
   "no_copy": 1,
   "read_only": 1
  },
  {
   "fieldname": "backend_references_section",
   "fieldtype": "Section Break",
   "label": "Backend References"
  },
  {
   "fieldname": "backend_references",
   "fieldtype": "Table",
   "label": "Backend References",
   "no_copy": 1,
   "options": "PV Backend Reference",
   "read_only": 1
  },
  {
   "fieldname": "amended_from",
   "fieldtype": "Link",
   "label": "Amended From",
   "no_copy": 1,
   "options": "Payment Voucher",
   "print_hide": 1,
   "read_only": 1,
   "search_index": 1
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party + Head Entry'",
   "fieldname": "combined_rows",
   "fieldtype": "Table",
   "label": "Combined Rows",
   "options": "PV Combined Row"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party + Head Entry'",
   "fieldname": "combined_section",
   "fieldtype": "Section Break",
   "label": "Party + Head Entries"
  }
 ],
 "grid_page_length": 50,
 "index_web_pages_for_search": 1,
 "is_submittable": 1,
 "links": [],
 "modified": "2026-04-16 08:07:46.678900",
 "modified_by": "Administrator",
 "module": "Dux Voucher",
 "name": "Payment Voucher",
 "owner": "Administrator",
 "permissions": [
  {
   "amend": 1,
   "cancel": 1,
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "Accounts User",
   "share": 1,
   "submit": 1,
   "write": 1
  },
  {
   "amend": 1,
   "cancel": 1,
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "Accounts Manager",
   "share": 1,
   "submit": 1,
   "write": 1
  }
 ],
 "row_format": "Dynamic",
 "rows_threshold_for_grid_search": 20,
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": [],
 "track_changes": 1
}
```

---

## dux_voucher/doctype/receipt_voucher/receipt_voucher.py

```python
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from dux_voucher.dux_voucher.api.utils import (
    _detect_party_type,
    _get_party_account,
    _get_account_currency,
    _validate_bank_cash_account,
    _submit_doc,
    _safe_cancel,
    get_mop_type,
)


class ReceiptVoucher(Document):

    def validate(self):
        self._validate_basics()
        if self.entry_mode == "Party-wise":
            self._validate_party_wise()
        elif self.entry_mode == "Head-wise":
            self._validate_head_wise()
        elif self.entry_mode == "Party + Head Entry":
            self._validate_combined()

    def _validate_basics(self):
        if not self.company:
            frappe.throw(_("Company is required"))
        if not self.posting_date:
            frappe.throw(_("Posting Date is required"))

    def _validate_party_wise(self):
        if not self.mode_of_payment:
            frappe.throw(_("Receipt Method is required"))
        if not self.received_in_account:
            frappe.throw(_("Received In Account is required"))
        if not self.party_rows:
            frappe.throw(_("Please add at least one party row"))

        _validate_bank_cash_account(self.received_in_account, "Received In Account")

        row_total = sum(flt(r.amount) for r in self.party_rows)
        if not flt(self.amount):
            self.amount = row_total
        elif abs(flt(self.amount) - row_total) > 0.005:
            frappe.throw(
                _("Amount ({0}) must equal sum of party rows ({1})").format(
                    flt(self.amount), row_total
                )
            )

        for row in self.party_rows:
            if not row.party:
                frappe.throw(_("Row {0}: Party is required").format(row.idx))
            if not flt(row.amount) or flt(row.amount) <= 0:
                frappe.throw(
                    _("Row {0}: Amount must be greater than zero").format(row.idx)
                )
            if not row.party_type:
                row.party_type = _detect_party_type(row.party)
                if not row.party_type:
                    frappe.throw(
                        _("Row {0}: '{1}' not found as Customer, "
                          "Supplier or Employee").format(row.idx, row.party)
                    )
            if not frappe.db.exists(row.party_type, row.party):
                frappe.throw(
                    _("Row {0}: {1} '{2}' does not exist").format(
                        row.idx, row.party_type, row.party
                    )
                )

    def _validate_head_wise(self):
        if not self.mode_of_payment:
            frappe.throw(_("Receipt Method is required"))
        if not self.received_in_account:
            frappe.throw(_("Received In Account is required"))
        if not self.account_rows:
            frappe.throw(_("Please add at least one account row"))

        _validate_bank_cash_account(self.received_in_account, "Received In Account")

        for row in self.account_rows:
            if not row.account:
                frappe.throw(_("Row {0}: Account is required").format(row.idx))
            if flt(row.debit) < 0 or flt(row.credit) < 0:
                frappe.throw(
                    _("Row {0}: Debit and Credit cannot be negative").format(row.idx)
                )
            if flt(row.debit) > 0 and flt(row.credit) > 0:
                frappe.throw(
                    _("Row {0}: A row cannot have both Debit and Credit").format(row.idx)
                )

        total_debit = sum(flt(r.debit) for r in self.account_rows)
        total_credit = sum(flt(r.credit) for r in self.account_rows)
        net_amount = total_credit - total_debit

        if net_amount <= 0:
            frappe.throw(
                _("Total Credit ({0}) must be greater than Total Debit ({1}). "
                  "The difference will be auto-debited to '{2}'").format(
                    total_credit, total_debit, self.received_in_account
                )
            )

        self.amount = net_amount

    def on_submit(self):
        refs = []
        try:
            if self.entry_mode == "Party-wise":
                refs = self._create_party_receipt_entries()
            elif self.entry_mode == "Head-wise":
                refs = self._create_head_wise_journal_entry()
            elif self.entry_mode == "Party + Head Entry":
                refs = self._create_combined_journal_entry()
        except frappe.ValidationError:
            raise
        except Exception as e:
            frappe.db.rollback()
            frappe.throw(
                _("Error creating backend entries: {0}").format(str(e))
            )

        for ref in refs:
            row = frappe.new_doc("RV Backend Reference")
            row.parent = self.name
            row.parenttype = "Receipt Voucher"
            row.parentfield = "backend_references"
            row.backend_doctype = ref["doctype"]
            row.backend_document = ref["name"]
            row.party = ref.get("party", "")
            row.amount = ref.get("amount", 0)
            row.insert(ignore_permissions=True)

        frappe.db.set_value("Receipt Voucher", self.name, "is_posted", 1)

    def on_cancel(self):
        refs = frappe.get_all(
            "RV Backend Reference",
            filters={"parent": self.name},
            fields=["backend_doctype", "backend_document"]
        )
        for ref in refs:
            _safe_cancel(ref.backend_doctype, ref.backend_document)

        frappe.db.set_value("Receipt Voucher", self.name, "is_posted", 0)

    def _create_party_receipt_entries(self):
        refs = []
        for row in self.party_rows:
            party_account = _get_party_account(
                row.party_type, row.party, self.company
            )
            if not party_account:
                frappe.throw(
                    _("Could not find ledger account for {0} '{1}'. "
                      "Please set default receivable/payable account "
                      "in Company or Party master.").format(
                        row.party_type, row.party
                    )
                )

            pe = frappe.new_doc("Payment Entry")
            pe.payment_type = "Receive"
            pe.company = self.company
            pe.posting_date = self.posting_date
            pe.mode_of_payment = self.mode_of_payment
            pe.party_type = row.party_type
            pe.party = row.party
            pe.paid_from = party_account
            pe.paid_to = self.received_in_account
            pe.paid_from_account_currency = _get_account_currency(
                party_account, self.company
            )
            pe.paid_to_account_currency = _get_account_currency(
                self.received_in_account, self.company
            )
            pe.paid_amount = flt(row.amount)
            pe.received_amount = flt(row.amount)
            pe.source_exchange_rate = 1
            pe.target_exchange_rate = 1
            pe.reference_no = self.reference_no or ""
            pe.reference_date = self.reference_date or self.posting_date
            pe.custom_remarks = 1
            pe.remarks = self.remarks or ""
            pe.custom_source_voucher_doctype = "Receipt Voucher"
            pe.custom_source_voucher = self.name

            _submit_doc(pe)
            refs.append({
                "doctype": "Payment Entry",
                "name": pe.name,
                "party": row.party,
                "amount": flt(row.amount)
            })
        return refs

    def _create_head_wise_journal_entry(self):
        mop_type = get_mop_type(self.mode_of_payment)
        voucher_type = "Cash Entry" if mop_type == "Cash" else "Bank Entry"

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = voucher_type
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or ""
        je.cheque_date = self.reference_date or None
        je.user_remark = self.remarks or ""
        je.custom_source_voucher_doctype = "Receipt Voucher"
        je.custom_source_voucher = self.name

        for row in self.account_rows:
            je.append("accounts", {
                "account": row.account,
                "debit_in_account_currency": flt(row.debit),
                "credit_in_account_currency": flt(row.credit),
                "cost_center": row.cost_center or self.cost_center or "",
                "project": row.project or self.project or "",
            })

        # Auto-add bank/cash debit row
        total_debit = sum(flt(r.debit) for r in self.account_rows)
        total_credit = sum(flt(r.credit) for r in self.account_rows)
        net_debit = total_credit - total_debit

        je.append("accounts", {
            "account": self.received_in_account,
            "debit_in_account_currency": net_debit,
            "credit_in_account_currency": 0,
            "cost_center": self.cost_center or "",
            "project": self.project or "",
        })

        _submit_doc(je)
        return [{
            "doctype": "Journal Entry",
            "name": je.name,
            "amount": net_debit
        }]

    # ------------------------------------------------------------------
    # Party + Head Entry -- validation
    # ------------------------------------------------------------------
    def _validate_combined(self):
        if not self.mode_of_payment:
            frappe.throw(_("Receipt Method is required"))
        if not self.received_in_account:
            frappe.throw(_("Received In Account is required"))
        if not self.combined_rows:
            frappe.throw(_("Please add at least one row"))

        _validate_bank_cash_account(self.received_in_account, "Received In Account")

        for row in self.combined_rows:
            if not row.account:
                frappe.throw(_("Row {0}: Account is required").format(row.idx))
            if flt(row.debit) < 0 or flt(row.credit) < 0:
                frappe.throw(
                    _("Row {0}: Debit and Credit cannot be negative").format(row.idx)
                )
            if flt(row.debit) > 0 and flt(row.credit) > 0:
                frappe.throw(
                    _("Row {0}: A row cannot have both Debit and Credit").format(row.idx)
                )
            # If party is set, validate it exists
            if row.party:
                if not row.party_type:
                    row.party_type = _detect_party_type(row.party)
                    if not row.party_type:
                        frappe.throw(
                            _("Row {0}: '{1}' not found as Customer, "
                              "Supplier or Employee").format(row.idx, row.party)
                        )
                if not frappe.db.exists(row.party_type, row.party):
                    frappe.throw(
                        _("Row {0}: {1} '{2}' does not exist").format(
                            row.idx, row.party_type, row.party
                        )
                    )

        total_debit = sum(flt(r.debit) for r in self.combined_rows)
        total_credit = sum(flt(r.credit) for r in self.combined_rows)
        net_amount = total_credit - total_debit

        if net_amount <= 0:
            frappe.throw(
                _("Total Credit ({0}) must be greater than Total Debit ({1}). "
                  "The difference will be auto-debited to '{2}'").format(
                    total_credit, total_debit, self.received_in_account
                )
            )

        self.amount = net_amount

    # ------------------------------------------------------------------
    # Party + Head Entry -- one Journal Entry with party mapping
    # ------------------------------------------------------------------
    def _create_combined_journal_entry(self):
        mop_type = get_mop_type(self.mode_of_payment)
        voucher_type = "Cash Entry" if mop_type == "Cash" else "Bank Entry"

        je = frappe.new_doc("Journal Entry")
        je.voucher_type = voucher_type
        je.company = self.company
        je.posting_date = self.posting_date
        je.cheque_no = self.reference_no or ""
        je.cheque_date = self.reference_date or None
        je.user_remark = self.remarks or ""
        je.custom_source_voucher_doctype = "Receipt Voucher"
        je.custom_source_voucher = self.name

        for row in self.combined_rows:
            je.append("accounts", {
                "account": row.account,
                "party_type": row.party_type or "",
                "party": row.party or "",
                "debit_in_account_currency": flt(row.debit),
                "credit_in_account_currency": flt(row.credit),
                "cost_center": row.cost_center or self.cost_center or "",
                "project": row.project or self.project or "",
            })

        # Auto-add bank/cash debit row
        total_debit = sum(flt(r.debit) for r in self.combined_rows)
        total_credit = sum(flt(r.credit) for r in self.combined_rows)
        net_debit = total_credit - total_debit

        je.append("accounts", {
            "account": self.received_in_account,
            "debit_in_account_currency": net_debit,
            "credit_in_account_currency": 0,
            "cost_center": self.cost_center or "",
            "project": self.project or "",
        })

        _submit_doc(je)
        return [{
            "doctype": "Journal Entry",
            "name": je.name,
            "amount": net_debit
        }]
```

---

## dux_voucher/doctype/receipt_voucher/receipt_voucher.json

```json
{
 "actions": [],
 "allow_rename": 1,
 "autoname": "naming_series:",
 "creation": "2026-03-29 07:48:02.584167",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": [
  "naming_series",
  "basic_details_section",
  "company",
  "mode_of_payment",
  "entry_mode",
  "basic_col_break",
  "posting_date",
  "received_in_account",
  "amount",
  "party_wise_section",
  "party_rows",
  "head_wise_section",
  "account_rows",
  "combined_section",
  "combined_rows",
  "reference_section",
  "reference_no",
  "cost_center",
  "reference_col_break",
  "reference_date",
  "project",
  "remarks_section",
  "remarks",
  "backend_tracking_section",
  "is_posted",
  "backend_references_section",
  "backend_references",
  "amended_from"
 ],
 "fields": [
  {
   "fieldname": "naming_series",
   "fieldtype": "Select",
   "label": "Naming Series",
   "no_copy": 1,
   "options": "RV-.YYYY.-",
   "set_only_once": 1
  },
  {
   "fieldname": "basic_details_section",
   "fieldtype": "Section Break",
   "label": "Basic Details"
  },
  {
   "bold": 1,
   "fieldname": "company",
   "fieldtype": "Link",
   "in_list_view": 1,
   "label": "Company",
   "options": "Company",
   "reqd": 1
  },
  {
   "fieldname": "mode_of_payment",
   "fieldtype": "Link",
   "label": "Receipt Method",
   "options": "Mode of Payment"
  },
  {
   "default": "Party-wise",
   "fieldname": "entry_mode",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Entry Mode",
   "options": "Party-wise\nHead-wise\nParty + Head Entry",
   "reqd": 1
  },
  {
   "fieldname": "basic_col_break",
   "fieldtype": "Column Break"
  },
  {
   "default": "Today",
   "fieldname": "posting_date",
   "fieldtype": "Date",
   "in_list_view": 1,
   "label": "Posting Date",
   "reqd": 1
  },
  {
   "fieldname": "received_in_account",
   "fieldtype": "Link",
   "label": "Received In Account",
   "options": "Account"
  },
  {
   "fieldname": "amount",
   "fieldtype": "Currency",
   "label": "Amount"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party-wise'",
   "fieldname": "party_wise_section",
   "fieldtype": "Section Break",
   "label": "Party-wise Entries"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party-wise'",
   "fieldname": "party_rows",
   "fieldtype": "Table",
   "label": "Party Rows",
   "options": "RV Party Row"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Head-wise'",
   "fieldname": "head_wise_section",
   "fieldtype": "Section Break",
   "label": "Head-wise Entries"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Head-wise'",
   "fieldname": "account_rows",
   "fieldtype": "Table",
   "label": "Account Rows",
   "options": "RV Account Row"
  },
  {
   "fieldname": "reference_section",
   "fieldtype": "Section Break",
   "label": "Reference / Allocation Details"
  },
  {
   "fieldname": "reference_no",
   "fieldtype": "Data",
   "label": "Reference No"
  },
  {
   "fieldname": "cost_center",
   "fieldtype": "Link",
   "label": "Cost Center",
   "options": "Cost Center"
  },
  {
   "fieldname": "reference_col_break",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "reference_date",
   "fieldtype": "Date",
   "label": "Reference Date"
  },
  {
   "fieldname": "project",
   "fieldtype": "Link",
   "label": "Project",
   "options": "Project"
  },
  {
   "fieldname": "remarks_section",
   "fieldtype": "Section Break",
   "label": "Remarks"
  },
  {
   "fieldname": "remarks",
   "fieldtype": "Text",
   "label": "Remarks"
  },
  {
   "fieldname": "backend_tracking_section",
   "fieldtype": "Section Break",
   "label": "Backend Tracking"
  },
  {
   "default": "0",
   "fieldname": "is_posted",
   "fieldtype": "Check",
   "label": "Is Posted",
   "no_copy": 1,
   "read_only": 1
  },
  {
   "fieldname": "backend_references_section",
   "fieldtype": "Section Break",
   "label": "Backend References"
  },
  {
   "fieldname": "backend_references",
   "fieldtype": "Table",
   "label": "Backend References",
   "no_copy": 1,
   "options": "RV Backend Reference",
   "read_only": 1
  },
  {
   "fieldname": "amended_from",
   "fieldtype": "Link",
   "label": "Amended From",
   "no_copy": 1,
   "options": "Receipt Voucher",
   "print_hide": 1,
   "read_only": 1,
   "search_index": 1
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party + Head Entry'",
   "fieldname": "combined_section",
   "fieldtype": "Section Break",
   "label": "Party + Head Entries"
  },
  {
   "depends_on": "eval:doc.entry_mode === 'Party + Head Entry'",
   "fieldname": "combined_rows",
   "fieldtype": "Table",
   "label": "Combined Rows",
   "options": "RV Combined Row"
  }
 ],
 "grid_page_length": 50,
 "index_web_pages_for_search": 1,
 "is_submittable": 1,
 "links": [],
 "modified": "2026-04-16 08:24:30.691360",
 "modified_by": "Administrator",
 "module": "Dux Voucher",
 "name": "Receipt Voucher",
 "owner": "Administrator",
 "permissions": [
  {
   "amend": 1,
   "cancel": 1,
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "Accounts User",
   "share": 1,
   "submit": 1,
   "write": 1
  },
  {
   "amend": 1,
   "cancel": 1,
   "create": 1,
   "delete": 1,
   "email": 1,
   "export": 1,
   "print": 1,
   "read": 1,
   "report": 1,
   "role": "Accounts Manager",
   "share": 1,
   "submit": 1,
   "write": 1
  }
 ],
 "row_format": "Dynamic",
 "rows_threshold_for_grid_search": 20,
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": [],
 "track_changes": 1
}
```

---

## dux_voucher/doctype/pv_combined_row/pv_combined_row.json

```json
{
 "actions": [],
 "allow_rename": 1,
 "creation": "2026-04-16 08:05:05.667964",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": [
  "party_type",
  "party",
  "party_name",
  "account",
  "current_balance",
  "balance_type",
  "debit",
  "credit",
  "cost_center",
  "project"
 ],
 "fields": [
  {
   "columns": 1,
   "fieldname": "party_type",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Party Type",
   "options": "\nCustomer\nSupplier\nEmployee"
  },
  {
   "columns": 2,
   "fieldname": "party",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Party"
  },
  {
   "columns": 2,
   "fieldname": "party_name",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Name",
   "read_only": 1
  },
  {
   "columns": 2,
   "fieldname": "account",
   "fieldtype": "Link",
   "in_list_view": 1,
   "label": "Account",
   "options": "Account",
   "reqd": 1
  },
  {
   "columns": 1,
   "fieldname": "current_balance",
   "fieldtype": "Currency",
   "in_list_view": 1,
   "label": "Balance",
   "no_copy": 1,
   "read_only": 1
  },
  {
   "columns": 1,
   "fieldname": "balance_type",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Dr/Cr",
   "no_copy": 1,
   "options": "\nDr\nCr\nNil",
   "read_only": 1
  },
  {
   "columns": 1,
   "default": "0",
   "fieldname": "debit",
   "fieldtype": "Currency",
   "in_list_view": 1,
   "label": "Debit"
  },
  {
   "columns": 1,
   "default": "0",
   "fieldname": "credit",
   "fieldtype": "Currency",
   "in_list_view": 1,
   "label": "Credit"
  },
  {
   "fieldname": "cost_center",
   "fieldtype": "Link",
   "label": "Cost Center",
   "options": "Cost Center"
  },
  {
   "fieldname": "project",
   "fieldtype": "Link",
   "label": "Project",
   "options": "Project"
  }
 ],
 "grid_page_length": 50,
 "index_web_pages_for_search": 1,
 "istable": 1,
 "links": [],
 "modified": "2026-04-16 08:05:05.667964",
 "modified_by": "Administrator",
 "module": "Dux Voucher",
 "name": "PV Combined Row",
 "owner": "Administrator",
 "permissions": [],
 "row_format": "Dynamic",
 "rows_threshold_for_grid_search": 20,
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": []
}
```

---

## dux_voucher/doctype/rv_combined_row/rv_combined_row.json

```json
{
 "actions": [],
 "allow_rename": 1,
 "creation": "2026-04-16 08:23:52.222425",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "field_order": [
  "party_type",
  "party",
  "party_name",
  "account",
  "current_balance",
  "balance_type",
  "debit",
  "credit",
  "cost_center",
  "project"
 ],
 "fields": [
  {
   "columns": 1,
   "fieldname": "party_type",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Party Type",
   "options": "\nCustomer\nSupplier\nEmployee"
  },
  {
   "columns": 2,
   "fieldname": "party",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Party"
  },
  {
   "columns": 2,
   "fieldname": "party_name",
   "fieldtype": "Data",
   "in_list_view": 1,
   "label": "Name",
   "read_only": 1
  },
  {
   "columns": 2,
   "fieldname": "account",
   "fieldtype": "Link",
   "in_list_view": 1,
   "label": "Account",
   "options": "Account",
   "reqd": 1
  },
  {
   "columns": 1,
   "fieldname": "current_balance",
   "fieldtype": "Currency",
   "in_list_view": 1,
   "label": "Balance",
   "no_copy": 1,
   "read_only": 1
  },
  {
   "columns": 1,
   "fieldname": "balance_type",
   "fieldtype": "Select",
   "in_list_view": 1,
   "label": "Dr/Cr",
   "no_copy": 1,
   "options": "\nDr\nCr\nNil",
   "read_only": 1
  },
  {
   "columns": 1,
   "default": "0",
   "fieldname": "debit",
   "fieldtype": "Currency",
   "in_list_view": 1,
   "label": "Debit"
  },
  {
   "columns": 1,
   "default": "0",
   "fieldname": "credit",
   "fieldtype": "Currency",
   "in_list_view": 1,
   "label": "Credit"
  },
  {
   "fieldname": "cost_center",
   "fieldtype": "Link",
   "label": "Cost Center",
   "options": "Cost Center"
  },
  {
   "fieldname": "project",
   "fieldtype": "Link",
   "label": "Project",
   "options": "Project"
  }
 ],
 "grid_page_length": 50,
 "index_web_pages_for_search": 1,
 "istable": 1,
 "links": [],
 "modified": "2026-04-16 08:23:52.222425",
 "modified_by": "Administrator",
 "module": "Dux Voucher",
 "name": "RV Combined Row",
 "owner": "Administrator",
 "permissions": [],
 "row_format": "Dynamic",
 "rows_threshold_for_grid_search": 20,
 "sort_field": "creation",
 "sort_order": "DESC",
 "states": []
}
```

---

## dux_voucher/doctype/pv_party_row/pv_party_row.json

```json
{
    "actions": [],
    "allow_rename": 1,
    "creation": "2026-03-29 07:19:08.237559",
    "doctype": "DocType",
    "editable_grid": 1,
    "engine": "InnoDB",
    "field_order": [
        "party",
        "party_type",
        "party_name",
        "amount",
        "current_balance",
        "balance_type"
    ],
    "fields": [
        {
            "columns": 4,
            "fieldname": "party",
            "fieldtype": "Data",
            "in_list_view": 1,
            "label": "Party",
            "reqd": 1
        },
        {
            "fieldname": "party_type",
            "fieldtype": "Select",
            "hidden": 1,
            "label": "Party Type",
            "options": "\nCustomer\nSupplier\nEmployee",
            "read_only": 1
        },
        {
            "columns": 3,
            "fieldname": "party_name",
            "fieldtype": "Data",
            "in_list_view": 1,
            "label": "Name",
            "read_only": 1
        },
        {
            "columns": 2,
            "fieldname": "amount",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Amount",
            "reqd": 1
        },
        {
            "columns": 2,
            "fieldname": "current_balance",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Balance",
            "no_copy": 1,
            "read_only": 1
        },
        {
            "columns": 1,
            "fieldname": "balance_type",
            "fieldtype": "Select",
            "in_list_view": 1,
            "label": "Dr/Cr",
            "no_copy": 1,
            "options": "\nDr\nCr\nNil",
            "read_only": 1
        }
    ],
    "grid_page_length": 50,
    "index_web_pages_for_search": 1,
    "istable": 1,
    "links": [],
    "modified": "2026-03-31 00:00:00.000000",
    "modified_by": "Administrator",
    "module": "Dux Voucher",
    "name": "PV Party Row",
    "owner": "Administrator",
    "permissions": [],
    "row_format": "Dynamic",
    "rows_threshold_for_grid_search": 20,
    "sort_field": "creation",
    "sort_order": "DESC",
    "states": []
}
```

---

## dux_voucher/doctype/pv_account_row/pv_account_row.json

```json
{
    "actions": [],
    "allow_rename": 1,
    "creation": "2026-03-29 07:19:53.350529",
    "doctype": "DocType",
    "editable_grid": 1,
    "engine": "InnoDB",
    "field_order": [
        "account",
        "current_balance",
        "balance_type",
        "debit",
        "credit",
        "cost_center",
        "project"
    ],
    "fields": [
        {
            "columns": 4,
            "fieldname": "account",
            "fieldtype": "Link",
            "in_list_view": 1,
            "label": "Account",
            "options": "Account",
            "reqd": 1
        },
        {
            "columns": 2,
            "fieldname": "current_balance",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Balance",
            "no_copy": 1,
            "read_only": 1
        },
        {
            "columns": 1,
            "fieldname": "balance_type",
            "fieldtype": "Select",
            "in_list_view": 1,
            "label": "Dr/Cr",
            "no_copy": 1,
            "options": "\nDr\nCr\nNil",
            "read_only": 1
        },
        {
            "columns": 2,
            "default": "0",
            "fieldname": "debit",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Debit"
        },
        {
            "columns": 2,
            "default": "0",
            "fieldname": "credit",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Credit"
        },
        {
            "columns": 2,
            "fieldname": "cost_center",
            "fieldtype": "Link",
            "in_list_view": 1,
            "label": "Cost Center",
            "options": "Cost Center"
        },
        {
            "columns": 2,
            "fieldname": "project",
            "fieldtype": "Link",
            "in_list_view": 1,
            "label": "Project",
            "options": "Project"
        }
    ],
    "grid_page_length": 50,
    "index_web_pages_for_search": 1,
    "istable": 1,
    "links": [],
    "modified": "2026-03-31 00:00:00.000000",
    "modified_by": "Administrator",
    "module": "Dux Voucher",
    "name": "PV Account Row",
    "owner": "Administrator",
    "permissions": [],
    "row_format": "Dynamic",
    "rows_threshold_for_grid_search": 20,
    "sort_field": "creation",
    "sort_order": "DESC",
    "states": []
}
```

---

## dux_voucher/doctype/rv_party_row/rv_party_row.json

```json
{
    "actions": [],
    "allow_rename": 1,
    "creation": "2026-03-29 07:19:08.237559",
    "doctype": "DocType",
    "editable_grid": 1,
    "engine": "InnoDB",
    "field_order": [
        "party",
        "party_type",
        "party_name",
        "amount",
        "current_balance",
        "balance_type"
    ],
    "fields": [
        {
            "columns": 4,
            "fieldname": "party",
            "fieldtype": "Data",
            "in_list_view": 1,
            "label": "Party",
            "reqd": 1
        },
        {
            "fieldname": "party_type",
            "fieldtype": "Select",
            "hidden": 1,
            "label": "Party Type",
            "options": "\nCustomer\nSupplier\nEmployee",
            "read_only": 1
        },
        {
            "columns": 3,
            "fieldname": "party_name",
            "fieldtype": "Data",
            "in_list_view": 1,
            "label": "Name",
            "read_only": 1
        },
        {
            "columns": 2,
            "fieldname": "amount",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Amount",
            "reqd": 1
        },
        {
            "columns": 2,
            "fieldname": "current_balance",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Balance",
            "no_copy": 1,
            "read_only": 1
        },
        {
            "columns": 1,
            "fieldname": "balance_type",
            "fieldtype": "Select",
            "in_list_view": 1,
            "label": "Dr/Cr",
            "no_copy": 1,
            "options": "\nDr\nCr\nNil",
            "read_only": 1
        }
    ],
    "grid_page_length": 50,
    "index_web_pages_for_search": 1,
    "istable": 1,
    "links": [],
    "modified": "2026-03-31 00:00:00.000000",
    "modified_by": "Administrator",
    "module": "Dux Voucher",
    "name": "RV Party Row",
    "owner": "Administrator",
    "permissions": [],
    "row_format": "Dynamic",
    "rows_threshold_for_grid_search": 20,
    "sort_field": "creation",
    "sort_order": "DESC",
    "states": []
}
```

---

## dux_voucher/doctype/rv_account_row/rv_account_row.json

```json
{
    "actions": [],
    "allow_rename": 1,
    "creation": "2026-03-29 07:19:53.350529",
    "doctype": "DocType",
    "editable_grid": 1,
    "engine": "InnoDB",
    "field_order": [
        "account",
        "current_balance",
        "balance_type",
        "debit",
        "credit",
        "cost_center",
        "project"
    ],
    "fields": [
        {
            "columns": 4,
            "fieldname": "account",
            "fieldtype": "Link",
            "in_list_view": 1,
            "label": "Account",
            "options": "Account",
            "reqd": 1
        },
        {
            "columns": 2,
            "fieldname": "current_balance",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Balance",
            "no_copy": 1,
            "read_only": 1
        },
        {
            "columns": 1,
            "fieldname": "balance_type",
            "fieldtype": "Select",
            "in_list_view": 1,
            "label": "Dr/Cr",
            "no_copy": 1,
            "options": "\nDr\nCr\nNil",
            "read_only": 1
        },
        {
            "columns": 2,
            "default": "0",
            "fieldname": "debit",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Debit"
        },
        {
            "columns": 2,
            "default": "0",
            "fieldname": "credit",
            "fieldtype": "Currency",
            "in_list_view": 1,
            "label": "Credit"
        },
        {
            "columns": 2,
            "fieldname": "cost_center",
            "fieldtype": "Link",
            "in_list_view": 1,
            "label": "Cost Center",
            "options": "Cost Center"
        },
        {
            "columns": 2,
            "fieldname": "project",
            "fieldtype": "Link",
            "in_list_view": 1,
            "label": "Project",
            "options": "Project"
        }
    ],
    "grid_page_length": 50,
    "index_web_pages_for_search": 1,
    "istable": 1,
    "links": [],
    "modified": "2026-03-31 00:00:00.000000",
    "modified_by": "Administrator",
    "module": "Dux Voucher",
    "name": "RV Account Row",
    "owner": "Administrator",
    "permissions": [],
    "row_format": "Dynamic",
    "rows_threshold_for_grid_search": 20,
    "sort_field": "creation",
    "sort_order": "DESC",
    "states": []
}
```

---

## dux_voucher/dux_voucher/doctype/payment_voucher/payment_voucher.js
_(See full source on branch `feature/combined-entry-mode`)_

Key functions (updated for Party + Head Entry):
- `_apply_entry_mode(frm)` — show/hide fields based on Party-wise / Head-wise / Contra / Party + Head Entry
- `_open_party_dialog(frm, cdt, cdn, prefill_txt)` — party search dialog (Party-wise mode)
- `_open_combined_party_dialog(frm, cdt, cdn, prefill_txt)` — NEW: party search dialog for Combined mode (auto-fills account)
- `_sum_party_rows(frm)` — auto-sum amount from party rows
- `_headwise_autofill_new_row / _headwise_balance_next_row` — auto-balance head-wise rows
- `_combined_autofill_new_row / _combined_balance_next_row` — NEW: auto-balance for combined mode
- `_show_headwise_totals(frm)` / `_show_combined_totals(frm)` — dashboard headline with debit/credit totals
- `_apply_payment_method_labels(frm)` — rename reference fields based on MOP

## dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.js
_(See full source on branch `feature/combined-entry-mode`)_

Mirror of payment_voucher.js with `_rv_` prefix. Uses `received_in_account` instead of `paid_from_account`. Head-wise and Combined auto-fill credit (not debit) on first row.

---

## GitHub Raw URLs for All Files

```
BASE: https://raw.githubusercontent.com/suranaaditya/dux_voucher/feature/combined-entry-mode

hooks.py:                       /dux_voucher/hooks.py
utils.py:                       /dux_voucher/utils.py
api/utils.py:                   /dux_voucher/dux_voucher/api/utils.py
api/payment_voucher_api.py:     /dux_voucher/dux_voucher/api/payment_voucher_api.py
payment_voucher.py:             /dux_voucher/dux_voucher/doctype/payment_voucher/payment_voucher.py
payment_voucher.js:             /dux_voucher/dux_voucher/doctype/payment_voucher/payment_voucher.js
payment_voucher.json:           /dux_voucher/dux_voucher/doctype/payment_voucher/payment_voucher.json
receipt_voucher.py:             /dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.py
receipt_voucher.js:             /dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.js
receipt_voucher.json:           /dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.json
pv_combined_row.json:           /dux_voucher/dux_voucher/doctype/pv_combined_row/pv_combined_row.json
rv_combined_row.json:           /dux_voucher/dux_voucher/doctype/rv_combined_row/rv_combined_row.json
custom_field.json:              /dux_voucher/fixtures/custom_field.json
```
