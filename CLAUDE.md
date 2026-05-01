# Dux Voucher — Claude Code Context

## Project Overview

A Tally-style simplified financial workflow layered on top of ERPNext v16.
Replaces complex Payment Entry / Journal Entry interactions with one-screen
vouchers, adds management-view reports (Day Book / Cash Book / Party Ledger),
ships polished Excel exports of the standard reports, and enforces
site-wide controls such as a configurable backdating policy. Built and
maintained for the JEWIPL / RGI institutional setup.

- **App name:** `dux_voucher`
- **GitHub:** https://github.com/suranaaditya/dux_voucher
- **Active branches**
  - `version-1` — main / production base
  - `feature/combined-entry-mode` — Party + Head Entry on PV/RV (rolled forward into ex-student)
  - `feature/ex-student-module` — Ex-Student opening balances, fee receipts, write-offs, plus Tally-style report Pages
  - `feature/formatted-tb-export` — Excel exports for the three Pages, formatted Trial Balance, and the site-wide Backdating Policy
  - `feature/new-student-module` — **current branch** (admission-fee receipts for incoming students; in progress)
  - `feat/ict-permissions-and-confirm` — Inter-Company Transfer permissions
- **Dev server:** `frappe@187.127.132.58`
- **Dev site:** `erp.jewonline.in` — Frappe `16.12.0`, ERPNext `16.10.0`
- **Bench path:** `/home/frappe/frappe-bench`
- **App path:** `/home/frappe/frappe-bench/apps/dux_voucher`

---

## App Structure

The app uses Frappe's nested-package layout — three levels deep — because
`dux_voucher.dux_voucher.<...>` was where the original code landed and the
nesting now carries history. **New code at the second level** (e.g.
`formatted_reports/`) imports as `dux_voucher.formatted_reports.<...>`
single-prefix; **older code at the third level** imports as
`dux_voucher.dux_voucher.<...>` double-prefix. Both work; just notice
which level a file sits at before writing dotted paths.

```
dux_voucher/                              repo root (pyproject, README, CLAUDE.md, .git)
└── dux_voucher/                          Python package root
    ├── hooks.py                          doc_events, app_include_js, fixtures, perms
    ├── patches.txt
    ├── modules.txt
    ├── public/
    │   └── js/formatted_tb_button.bundle.js   "Download Formatted TB" injector
    ├── fixtures/custom_field.json
    ├── patches/
    │   ├── v1_0/seed_backdating_rules.py      seeds 7 default rules
    │   └── v1_1/backfill_date_field.py        fills date_field for PO
    ├── formatted_reports/                     formatted Excel exports (single-prefix)
    │   ├── PLAN.md                            v5 design contract for TB
    │   ├── build_v5_reference.py              visual logic source-of-truth
    │   └── trial_balance/
    │       ├── api.py                         export_formatted_tb endpoint
    │       ├── builder.py                     openpyxl two-sheet workbook
    │       └── tests/test_builder.py
    └── dux_voucher/                           submodule with all doctypes (double-prefix)
        ├── api/
        │   ├── utils.py                       shared helpers
        │   ├── payment_voucher_api.py
        │   ├── ex_student_api.py
        │   ├── ic_transfer_api.py
        │   ├── reports_api.py                 ledger / daybook / cashbook data
        │   ├── reports_export.py              xlsx exports for those Pages
        │   └── backdating.py                  posting-date enforcement
        ├── doctype/
        │   ├── payment_voucher/  + child rows + backend ref
        │   ├── receipt_voucher/  + child rows + backend ref
        │   ├── ex_student/       + opening_row / opening_batch / receipt /
        │   │                       writeoff / ledger_entry
        │   ├── inter_company_transfer/
        │   ├── ic_company_account_mapping/
        │   ├── inter_company_transfer_settings/
        │   ├── dux_backdating_settings/   site-wide posting-date policy
        │   ├── dux_backdating_rule/
        │   └── dux_backdating_bypass_role/
        ├── page/
        │   ├── dux_ledger/                    Party Ledger
        │   ├── dux_daybook/                   Day Book
        │   └── dux_cashbook/                  Cash & Bank Book
        ├── report/
        │   ├── ex_student_outstanding/
        │   └── ict_pending_confirmation/
        ├── print_format/                      polished print formats
        ├── tests/test_backdating.py
        └── utils.py                           cancel cascade for PE/JE
```

---

## Features

### 1. Payment Voucher / Receipt Voucher (one-screen replacements for PE/JE)

Tally-style entry that posts to ERPNext via Payment Entry or Journal
Entry under the hood. Entry modes:

- **Payment Voucher** — Party-wise (one PE per row) · Head-wise (one JE) ·
  Contra Entry (PE Internal Transfer) · **Party + Head Entry** (one JE
  mixing parties and account heads, with auto-resolution of party
  ledgers via `get_party_default_account`)
- **Receipt Voucher** — Party-wise · Head-wise · Party + Head Entry
  (mirror of PV with credit-first auto-fill)

Cancel-cascade: cancelling a parent voucher cancels every backend PE/JE;
cancelling a backend PE/JE directly cancels the parent voucher
(`dux_voucher/utils.py`).

### 2. Ex-Student Module

Tracks outstanding fee balances for graduated students who still owe the
institution (handed over after the lifecycle software wrote off the
ledger). Submittable doctypes:

- **Ex Student** — per-student master with mixed Dr/Cr opening balance
- **Ex Student Opening Batch** — bulk-upload opening balances with CSV
  import
- **Ex Student Receipt** — fee collection → posts JE
- **Ex Student Writeoff** — partial / full writeoff → posts JE
- **Ex Student Ledger Entry** — denormalised running-balance rows for
  the Outstanding report

`Ex Student Outstanding` (Script Report) shows current Dr balance per
student.

### 3. Inter-Company Transfer

Two-step settlement between sister companies (cash/bank movement on
company A is acknowledged via confirmation on company B). Permission-
scoped via custom hooks (`api/ic_transfer_api.py`).

### 4. Tally-style Pages — Day Book / Cash Book / Party Ledger

Custom Frappe Pages (not Reports) styled to match the on-screen
expectations of an accountant familiar with Tally:

- **Dux Ledger** (`/app/dux-ledger`) — party / account ledger statement
  with running balance, search-as-you-type for accounts and parties
- **Dux Daybook** (`/app/dux-daybook`) — chronological voucher list,
  voucher-type filter
- **Dux Cashbook** (`/app/dux-cashbook`) — bank/cash account ledger

Each page has filters, an in-window print (portrait/landscape), and a
green **Excel** button → calls `api/reports_export.py`. The Excel
output uses openpyxl with banded rows, frozen header, INR number
format, and Dr/Cr suffix on balance cells.

### 5. Formatted Trial Balance

A **"Download Formatted TB"** button is added to ERPNext's standard
Trial Balance Script Report. Clicking it produces a polished two-sheet
xlsx — `Summary` (KPI dashboard view with tie-status banner) and
`Detail` (full hierarchical TB) — both sheets driven from the same
formula references so they cannot drift.

The visual contract is locked in `formatted_reports/PLAN.md` v5. The
button is injected via `app_include_js` (and **not** Frappe's Client
Script DocType, because the `view` enum on Frappe 16.12 only allows
`List|Form` — not `Report`). The bundle uses `Object.defineProperty`
on `frappe.query_reports["Trial Balance"]` to wrap the report's
`onload` regardless of when ERPNext lazy-loads its module.

### 6. Backdating Policy (site-wide)

A System-Manager-only Single doctype `Dux Backdating Settings`
controls whether back-dated and forward-dated postings are accepted on
seven controlled doctypes. Each rule has independent `allow_*` flags
plus day caps; **`max_days_* = 0` is treated as unlimited**, mirroring
the natural "checked = open, integer = limit" semantics. A global
bypass-roles list short-circuits the check for users holding any of
those roles.

The seven controlled doctypes:

- Payment Voucher · Receipt Voucher · Ex Student Receipt · Journal Entry
- Purchase Order (uses `transaction_date`, configured per-rule via the
  optional `date_field` override)
- Purchase Receipt · Purchase Invoice

Rules carry a `date_field` column so future doctypes with non-standard
fieldnames can be wired in via the Settings page — no code change.

Enforcement is a single `validate` hook (`api/backdating.enforce`)
wired in `hooks.py`. Sub-millisecond no-op when the master switch is
off, so the cost on every controlled-doctype save is negligible
unless the policy is actively enforced.

### 7. New Student Admission Receipts (in progress, this branch)

Admission-fee counter for incoming students. Four doctypes (planned):

- **Course** + **Course Fee Head** (per-course allowed heads — sibling
  doctype linked to Course)
- **Student** master (auto-created from receipt's inline dialog;
  dedup on name + father + course; `STU-####` autoname with
  `title_field` for human-readable display)
- **Student Fee Receipt** (submittable; multi-head split → single JE
  crediting `Admission Fee / Registration` under the
  `University Fee Payable` group; `Dr` to bank/cash)

Print format from day one. Will be added to the Backdating Policy as
the eighth controlled doctype.

---

## Key Business Logic

- Auto-detect party type (Customer / Supplier / Employee) from a single
  search dialog on the Vouchers
- Party search dialog with keyboard navigation (arrow keys + enter)
- Amount auto-sums from party rows; head-wise auto-balances
- **Party + Head Entry**: party selection auto-fills the ledger account
  via `get_party_default_account`; backend JE populates `party_type` +
  `party` so ERPNext's native party validation runs (Sundry Creditors
  for Supplier, Sundry Debtors for Customer, etc.)
- Cancel a voucher → cancels all backend entries; cancel a backend
  entry directly → cancels the parent voucher
- `custom_remarks = 1` on Payment Entry; Reference No → UTR (Bank/UPI)
  or Cheque Number (Cheque)
- Backdating policy `validate` hook is the only cross-cutting guard;
  individual doctype controllers don't second-guess the date

---

## Pending Work

- [ ] **New Student Admission Receipts** — phased build in progress on
      `feature/new-student-module` (Phase 1: masters → Phase 2:
      receipt + JE → Phase 3: print format → Phase 4: backdating
      wiring)
- [ ] Smoke tests for Formatted TB and Backdating (planned in
      `formatted_reports/PLAN.md` §5.3 — needs the marker assertion
      against the built bundle)
- [ ] Eventual merge of accumulated feature branches back into
      `version-1` so main reflects production reality

## Recently Completed

- [x] **Backdating Policy** — Single doctype + 3 child tables + seed
      patch + backfill patch + per-rule `date_field` override; 25 unit
      tests; wired into 7 controlled doctypes via `doc_events`
- [x] **Formatted Trial Balance** — two-sheet polished xlsx, hooked via
      `app_include_js` with `Object.defineProperty` setter to survive
      ERPNext's lazy load
- [x] **Excel exports** for Dux Ledger / Day Book / Cash & Bank Book —
      green button on each Page, openpyxl-built workbook
- [x] **Ex Student Receipt and Ex Student Writeoff `posting_date`
      unlocks** — sister fixes to the PV/RV revert (commit `72cdc4c`)
- [x] **Combined Entry Mode** (Party + Head) on PV/RV from earlier
      branches — merged into ex-student tip

---

## Deployment

```bash
# On dev server — pick up changes from a branch
cd /home/frappe/frappe-bench/apps/dux_voucher
git pull origin <branch>

cd /home/frappe/frappe-bench
bench --site erp.jewonline.in migrate     # only when doctypes / patches change
bench build --app dux_voucher              # only when JS / CSS bundles change

# IMPORTANT: bench restart is a NO-OP on this host. Always reload via SIGHUP:
pkill -HUP -f "gunicorn.*frappe"
```

Browser hard-refresh (Ctrl+Shift+R) when a JS bundle hash changes.

**Production flow:** edits land on dev first → `git push origin
<branch>` → on production server `git pull` + the migrate/build/HUP
trio above. No `bench restart` anywhere.

---

## Source layout cheatsheet

Notable cross-cutting files when you need to find something fast:

| Concern | File |
|---|---|
| `doc_events`, `app_include_js`, fixtures, permissions | `dux_voucher/hooks.py` |
| Cancel-cascade between PE/JE and parent vouchers | `dux_voucher/dux_voucher/utils.py` |
| Posting-date enforcement | `dux_voucher/dux_voucher/api/backdating.py` |
| Page reports + xlsx exports | `dux_voucher/dux_voucher/api/reports_api.py`, `reports_export.py` |
| Formatted TB workbook builder | `dux_voucher/formatted_reports/trial_balance/builder.py` |
| Site-wide settings doctype | `dux_voucher/dux_voucher/doctype/dux_backdating_settings/` |
| Voucher controllers | `dux_voucher/dux_voucher/doctype/{payment,receipt}_voucher/` |
| Ex-student lifecycle | `dux_voucher/dux_voucher/doctype/ex_student*/` |

For exact source, browse on GitHub or `git ls-files` on the server.
