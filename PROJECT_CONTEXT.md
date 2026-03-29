# Dux Voucher — Project Context

## What is this app?
A Tally-style simplified Payment and Receipt Voucher app for ERPNext v16.
Replaces complex Payment Entry / Journal Entry workflow with two simple vouchers.

## GitHub
- Repo: https://github.com/suranaaditya/dux_voucher
- Branch: version-1
- Owner: suranaaditya (Aditya Surana - Dux DigiTech)

## Servers
- Development server: frappe@187.127.132.58
- Dev site: erp.jewonline.in
- Bench path: /home/frappe/frappe-bench
- App path: /home/frappe/frappe-bench/apps/dux_voucher
- ERPNext version: v16
- Frappe version: v16

## App Structure
```
dux_voucher/
└── dux_voucher/
    ├── hooks.py              — fixtures, doc_events, after_install
    ├── utils.py              — cascade cancel from PE/JE to parent voucher
    └── dux_voucher/
        ├── api/
        │   ├── utils.py      — shared helpers (detect party, get account, submit_doc etc)
        │   └── payment_voucher_api.py  — all @frappe.whitelist() APIs
        ├── doctype/
        │   ├── payment_voucher/
        │   │   ├── payment_voucher.py   — controller
        │   │   └── payment_voucher.js   — UI logic
        │   ├── receipt_voucher/
        │   │   ├── receipt_voucher.py
        │   │   └── receipt_voucher.js
        │   ├── pv_party_row/
        │   ├── pv_account_row/
        │   ├── pv_backend_reference/
        │   ├── rv_party_row/
        │   ├── rv_account_row/
        │   └── rv_backend_reference/
        └── fixtures/
            └── custom_field.json   — custom fields on PE and JE
```

## DocTypes Created
| DocType | Naming | Submittable |
|---|---|---|
| Payment Voucher | PV-.YYYY.- | Yes |
| Receipt Voucher | RV-.YYYY.- | Yes |
| PV Party Row | child table | No |
| PV Account Row | child table | No |
| PV Backend Reference | child table | No |
| RV Party Row | child table | No |
| RV Account Row | child table | No |
| RV Backend Reference | child table | No |

## Custom Fields Added to ERPNext
| DocType | Field | Purpose |
|---|---|---|
| Payment Entry | custom_source_voucher_doctype | Link back to parent voucher type |
| Payment Entry | custom_source_voucher | Link back to parent voucher name |
| Journal Entry | custom_source_voucher_doctype | Link back to parent voucher type |
| Journal Entry | custom_source_voucher | Link back to parent voucher name |

## Payment Voucher — Entry Modes
1. **Party-wise** — Creates one Payment Entry (type=Pay) per party row
   - Paid From Account = Bank/Cash (from Basic Details)
   - Party ledger auto-detected from Customer/Supplier/Employee master
   - Multiple parties in one voucher

2. **Head-wise** — Creates one Journal Entry (Bank/Cash type)
   - User enters debit/credit rows
   - Bank/Cash credit row auto-added from Paid From Account
   - Net amount = Total Debit - Total Credit from table
   - Accounting: Expense DR, Bank/Cash CR (auto), TDS CR (if applicable)

3. **Contra Entry** — Creates Payment Entry (type=Internal Transfer)
   - Transfer From → Transfer To (both must be Bank/Cash accounts)

## Receipt Voucher — Entry Modes
1. **Party-wise** — Creates one Payment Entry (type=Receive) per party row
   - Received In Account = Bank/Cash (from Basic Details)
   
2. **Head-wise** — Creates one Journal Entry
   - Bank/Cash debit row auto-added from Received In Account
   - Net amount = Total Credit - Total Debit from table

## Key Business Logic
- Auto-detect party type (Customer/Supplier/Employee) from single search
- Party search dialog with keyboard navigation (arrow keys + enter)
- Amount auto-sums from party rows
- Head-wise: first row auto-fills, next rows auto-balance
- Cancel voucher → cancels all backend entries
- Cancel backend entry directly → cancels parent voucher
- custom_remarks = 1 set on Payment Entry for custom remarks
- Reference No → UTR Number (Bank/UPI) or Cheque Number (Cheque)
- Cost Center and Project filters scoped to selected company

## API Endpoints
All in `dux_voucher.dux_voucher.api.payment_voucher_api`:
- `search_party` — search Customer+Supplier+Employee in one query
- `get_party_details` — get party_type and display name
- `get_mop_account_type` — get Bank/Cash type for Mode of Payment
- `validate_backend_entry` — dry run validation

## Shared Utilities
All in `dux_voucher.dux_voucher.api.utils`:
- `_detect_party_type` — find if party is Customer/Supplier/Employee
- `_get_party_account` — get ledger account for party
- `_get_account_currency` — get account currency
- `_validate_bank_cash_account` — validate account is Bank or Cash type
- `_submit_doc` — insert + submit with proper error handling
- `_safe_cancel` — cancel backend doc safely
- `get_mop_type` — get Bank/Cash type for MOP

## What is Pending / Next Steps
- [ ] Print formats for Payment Voucher and Receipt Voucher
- [ ] Install on Frappe Cloud production site
- [ ] Test with real data at client site (jewonline.in)

## How to Install on a New Site
```bash
bench get-app https://github.com/suranaaditya/dux_voucher --branch version-1
bench --site SITENAME install-app dux_voucher
bench --site SITENAME migrate
bench build --app dux_voucher
bench restart
```

## How to Update After Code Changes
```bash
cd ~/frappe-bench/apps/dux_voucher
git add .
git commit -m "Description of changes"
git push origin version-1

# On target server
cd ~/frappe-bench
bench get-app dux_voucher  # or git pull in apps/dux_voucher
bench --site SITENAME migrate
bench build --app dux_voucher
bench restart
```

## How to Start a New Chat with Context
1. Upload this file PROJECT_CONTEXT.md to the new chat
2. Say: "I am continuing development on this Frappe/ERPNext app. Please read the PROJECT_CONTEXT.md file I have uploaded to understand what has been built so far."