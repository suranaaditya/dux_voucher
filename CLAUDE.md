# Dux Voucher — Claude Code Context

## Project Overview

A Tally-style simplified financial workflow layered on top of ERPNext v16.
Replaces complex Payment Entry / Journal Entry interactions with one-screen
vouchers, adds management-view reports (Day Book / Cash Book / Ledger /
Party Ledger / Party Trial Balance / Student Ledger), ships polished Excel
exports of the standard reports, and enforces site-wide controls such as a
configurable backdating policy. Built and maintained for the JEWIPL / RGI
institutional setup.

- **App name:** `dux_voucher`
- **GitHub:** https://github.com/suranaaditya/dux_voucher
- **Active branches**
  - `version-1` — the original main line. **Stale — production does not track it.** Kept as history until the feature branches are merged back.
  - `feature/combined-entry-mode` — Party + Head Entry on PV/RV (rolled forward into ex-student)
  - `feature/ex-student-module` — Ex-Student opening balances, fee receipts, write-offs, plus Tally-style report Pages
  - `feature/formatted-tb-export` — Excel exports for the three Pages, formatted Trial Balance, and the site-wide Backdating Policy
  - `feature/new-student-module` — **current branch, and what dev + production both run.** Everything below has accumulated on this one tip: admission-fee receipts and refunds, the retained-fee income flow, and the whole Tally-style report layer. Do not expect the other feature branches to carry any of it.
  - `feat/ict-permissions-and-confirm` — Inter-Company Transfer permissions
- **Stack:** Frappe `16.12.0`, ERPNext `16.10.0`
- **Environments:** dev and production both deploy this repo's
  `feature/new-student-module` branch. There is **no separate release
  branch** — both run the same tip, so anything pushed reaches both.
  Dev additionally carries 30+ other in-house apps; production does not.
- **Server details are deliberately not recorded here.** This repository
  is public. Host names, IPs, bench paths, site names and any credentials
  live in the team's private notes — never in a committed file. Commands
  below use `<bench>` and `<site>` placeholders.

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
    │   ├── v1_0/seed_backdating_rules.py      seeds one rule per SUPPORTED_DOCTYPES
    │   ├── v1_1/backfill_date_field.py        fills date_field for PO
    │   ├── v1_2/seed_student_fee_receipt_rule.py   adds the 8th rule on existing sites
    │   ├── v1_3/seed_ex_student_refund_rule.py     adds the 9th
    │   ├── v1_4/seed_student_fee_refund_rule.py    adds the 10th
    │   └── v1_5/seed_trial_balance_roles.py        the two TB roles
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
        │   ├── reports_api.py                 ledger / daybook / cashbook / party TB /
        │   │                                  student ledger data + T-account helper
        │   ├── reports_export.py              xlsx exports for those Pages
        │   ├── backdating.py                  posting-date enforcement
        │   ├── student_fee.py                 admission-fee + retained-income accounts,
        │   │                                  book_income, paid/remaining helpers
        │   ├── trial_balance.py               whitelisted API behind the TB page;
        │   │                                  every endpoint calls require_access()
        │   └── tb_aggregate.py                monthly pre-aggregation + nightly job
        ├── doctype/
        │   ├── payment_voucher/  + child rows + backend ref
        │   ├── receipt_voucher/  + child rows + backend ref
        │   ├── ex_student/       + opening_row / opening_batch / receipt /
        │   │                       refund / writeoff / ledger_entry
        │   ├── inter_company_transfer/
        │   ├── ic_company_account_mapping/
        │   ├── inter_company_transfer_settings/
        │   ├── dux_backdating_settings/   site-wide posting-date policy
        │   ├── dux_backdating_rule/
        │   ├── dux_backdating_bypass_role/
        │   ├── course/                        admission-fee module — global
        │   ├── course_fee_head/               sibling, course-scoped
        │   ├── student/                       per-company; STU-####;
        │   │                                  dedup on (name, father, course, company)
        │   ├── student_fee_receipt/           submittable; SFR-.YYYY.-
        │   ├── student_fee_receipt_head/      child rows on receipt
        │   ├── student_fee_refund/            submittable; SRF-.YYYY.- (+ income_* fields)
        │   ├── student_fee_refund_head/       child rows on refund
        │   ├── student_fee_settings/          Single; retained-income account override
        │   └── dux_tb_period_balance/         pre-aggregated TB, one row per
        │                                      (period, company, account, party)
        ├── page/
        │   ├── dux_ledger/                    Ledger Statement
        │   ├── dux_daybook/                   Day Book
        │   ├── dux_cashbook/                  Cash & Bank Book
        │   ├── dux_party_ledger/              Party Ledger (System Manager)
        │   ├── dux_party_trial_balance/       Party Trial Balance → click-through
        │   │                                  to Party Ledger
        │   ├── dux_student_ledger/            Student Ledger (ex + new student)
        │   └── dux_trial_balance/             Trial Balance — the primary UI
        ├── report/
        │   ├── ex_student_outstanding/
        │   ├── ict_pending_confirmation/
        │   ├── admission_fee_register/        flat list + KPI summary
        │   ├── student_fee_refund_income/     retained fee → income; KPI cards +
        │                                      per-row "Book as income" action
        │   └── dux_trial_balance/             the TB engine; the page calls it
        ├── print_format/                      polished print formats
        │   ├── dux_payment_voucher / dux_receipt_voucher
        │   ├── ex_student_receipt / ex_student_refund / ex_student_writeoff
        │   └── student_fee_receipt / student_fee_refund
        ├── tests/
        │   ├── test_backdating.py             27 tests
        │   ├── test_student_masters.py        19 tests (Course/Fee Head/Student)
        │   ├── test_student_fee_receipt.py    13 tests (validate + FY helper)
        │   └── test_student_fee_refund_income.py   7 tests (income-account
        │                                      resolver guards + balance helper)
        └── utils.py                           cancel cascade for PE/JE + income JE
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
- **Ex Student Receipt** — fee collection → posts JE (Dr Bank/Cash, Cr
  Receivable)
- **Ex Student Refund** — pay a credit balance back → posts JE (Dr
  Receivable, Cr Bank/Cash); mirror of Receipt with reversed legs,
  orange-accented print format, soft-warn on Dr balance and overpay
- **Ex Student Writeoff** — partial / full writeoff → posts JE
- **Ex Student Ledger Entry** — denormalised running-balance rows for
  the Outstanding report

`Ex Student Outstanding` (Script Report) shows current Dr balance per
student.

### 3. Inter-Company Transfer

Two-step settlement between sister companies (cash/bank movement on
company A is acknowledged via confirmation on company B). Permission-
scoped via custom hooks (`api/ic_transfer_api.py`).

### 4. Tally-style Pages — Day Book / Cash Book / Ledger / Party TB

Custom Frappe Pages (not Reports) styled to match the on-screen
expectations of an accountant familiar with Tally:

- **Dux Ledger** (`/app/dux-ledger`) — party / account ledger statement
  with running balance, search-as-you-type for accounts and parties
- **Dux Daybook** (`/app/dux-daybook`) — chronological voucher list,
  voucher-type filter
- **Dux Cashbook** (`/app/dux-cashbook`) — bank/cash account ledger
- **Dux Party Ledger** (`/app/dux-party-ledger`) — parties-only picker
  (`search_ledger(parties_only=1)`), System Manager role-gated
- **Dux Party Trial Balance** (`/app/dux-party-trial-balance`) — every
  party of one type (Customer / Supplier / Employee) in a company with
  Opening Dr/Cr, period Debit, period Credit and Closing Dr/Cr per party.
  Column layout matches ERPNext's "Trial Balance for Party". Backend
  `get_party_trial_balance` runs two batched GL queries grouped by party,
  reusing the ledger's opening rule and cancelled-voucher exclusion.
  Single Party column with a party search box; a `show_zero` toggle; and
  **clicking a party opens that exact party** in the Party Ledger page
  (same company + party) via `frappe.route_options` → `applyRouteOptions`.
- **Dux Student Ledger** (`/app/dux-student-ledger`) — unified Dr/Cr
  statement for a single **Ex Student** or **New Student**, picked via a
  company-scoped toggle + student picker. NOT GL-Entry based (neither
  student kind is a GL party, and both share one company-wide account):
  the ex-student side reads the `Ex Student Ledger Entry` table, the
  new-student side unions submitted Student Fee Receipts (→ Credit) and
  Refunds (→ Debit). Backend `get_student_ledger` / `search_students`
  return the SAME dict shape as `get_ledger_statement`, so the page
  renderer and the openpyxl workbook builder are reused verbatim.
  Role-gated (System Manager / Accounts Manager / Accounts User).

Each page has filters, an in-window print (portrait/landscape), and a
green **Excel** button → calls `api/reports_export.py`. The Excel
output uses openpyxl with banded rows, frozen header, INR number
format, and Dr/Cr suffix on balance cells.

#### 4a. Ledger presentation rules (apply to all four ledger surfaces)

These are display-time rules. None of them write GL, and all are
retroactive for existing entries.

- **Strict T-account layout** — the opening balance renders in its
  NATURAL column (Dr balance → Debit, Cr balance → Credit) and the
  closing balance is carried down as a **balancing contra on the
  OPPOSITE column**, so the bottom row ties exactly: Total Debit ==
  Total Credit. Driven by the single helper
  `reports_api._taccount_summary(ob_net, period_dr, period_cr)` so
  screen, print and Excel cannot drift. Before this, opening showed
  only in the Balance column and the footer summed period movement
  alone, which never reconciled to the closing.
- **"Various" drill-down** — a row whose counter side spans 2+ accounts
  renders as "Various". `get_ledger_statement` attaches a per-row
  `breakdown` list (counter account + amount on the opposite side),
  fetched in one batched GL query keyed by `voucher_no`, only for those
  rows. Pages get a "Show details" toolbar toggle plus a per-row
  chevron; print renders whatever is currently expanded; Excel writes
  indented sub-rows.
- **Party surfaced in Particulars** — GL `against` only reflects the
  OPPOSITE Dr/Cr side, so a party on the SAME side as the viewed row
  (the supplier credit next to a TDS credit) never reaches it, and the
  TDS ledger showed the expense head instead of the deductee. Rows with
  no party of their own now surface the **voucher's** party, falling
  back to "First & N more" for multi-party vouchers and to the old
  against/account text when there is none. Ledger Statement and Cash &
  Bank Book inherit it; Party Ledger, Day Book and Party TB are
  unchanged.
- **RGI house convention (inverted To/By)** — applies to the party
  ledger and to Bank/Cash accounts (Cash & Bank Book): Dr → "By",
  Cr → "To". Plain non-bank account views keep the textbook rule.
- **Cancelled vouchers hidden** — ERPNext keeps the original GL rows
  *and* posts sign-flipped reversals, **both with `is_cancelled=0`**.
  Filter on the parent's `docstatus=2` instead, joining GL Entry → PE/JE.
- **Responsive** — all five report pages shrink to fit narrow screens
  via two `@media` breakpoints, and long unbroken UPI/reference strings
  in remark rows wrap (`overflow-wrap:anywhere`) instead of setting the
  table's minimum width and pushing Debit/Credit off-screen.

#### 4b. Day Book specifics

- **Date on every row** (Date column; the per-day divider was removed).
- **Debit and Credit columns**, not a single Amount column — and the
  amount sits on **one side only**, by voucher nature: Receipts / Sales
  on Credit, Payments / Journals / Contra on Debit, via
  `_DAYBOOK_CREDIT_TYPES`. The empty side reads "—". Column totals are
  per-side sums and **do not tie** — a day book's don't.
- **Particulars** — `"Various"` is replaced with per-voucher-type
  labels: Purchase Receipt → `supplier_name`; Stock Entry →
  `custom_department` (falls back to `stock_entry_type`, guarded by
  `frappe.db.has_column`); PV / RV Head-wise → first Account Row +
  `" & more"` if >1; **any** Journal Entry without parties → first JE
  Account + `" & more"`.

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
ten controlled doctypes. Each rule has independent `allow_*` flags
plus day caps; **`max_days_* = 0` is treated as unlimited**, mirroring
the natural "checked = open, integer = limit" semantics. A global
bypass-roles list short-circuits the check for users holding any of
those roles.

The ten controlled doctypes:

- Payment Voucher · Receipt Voucher · Ex Student Receipt · Ex Student Refund · Student Fee Receipt · Student Fee Refund · Journal Entry
- Purchase Order (uses `transaction_date`, configured per-rule via the
  optional `date_field` override)
- Purchase Receipt · Purchase Invoice

Rules carry a `date_field` column so future doctypes with non-standard
fieldnames can be wired in via the Settings page — no code change.

Enforcement is a single `validate` hook (`api/backdating.enforce`)
wired in `hooks.py`. Sub-millisecond no-op when the master switch is
off, so the cost on every controlled-doctype save is negligible
unless the policy is actively enforced.

**Adding an 11th needs THREE edits, not one:**

1. `SUPPORTED_DOCTYPES` in `doctype/dux_backdating_settings/dux_backdating_settings.py`
2. the `target_doctype` **Select options string** in
   `doctype/dux_backdating_rule/dux_backdating_rule.json` — *and bump its
   `modified` timestamp* so migrate re-syncs it
3. a new `patches/v1_N/seed_…_rule.py` + a line in `patches.txt`

Missing step 2 makes `bench migrate` fail with
`Row #N: DocType cannot be "X". It should be one of …`.

### 7. New Student Admission Receipts

Admission-fee counter for incoming students. Doctypes plus reports and
print formats:

- **Course** — *global* (not company-scoped); autoname is the course
  name itself (`field:course_name`) so Link pickers display "MBA"
  rather than a synthetic id; `unique=1` enforces single-row-per-name
  at the DB level.
- **Course Fee Head** — sibling doctype linked to Course; defines the
  fee-head labels valid for that course (Tuition, Hostel, etc.). The
  receipt's head picker is `set_query`-filtered to the student's
  course so MBA receipts can't see BCom heads.
- **Student** — per-company; `STU-####` autoname; dedup on
  `(student_name, father_name, course, company)` — same person at
  two institutions stays as two records by design. `student_display`
  is recomputed on every save and used as `title_field`. Mobile
  number normalised + Indian-format-validated (`^[6-9]\d{9}$` after
  stripping `+91`/`91` prefix).
- **Student Fee Receipt** (submittable, `SFR-.YYYY.-`) — multi-head
  split into a child table; on submit posts a **single 2-line JE**
  crediting `Admission/Registration Fee (Provisional) - {abbr}` under
  the `Admission Fee (Provisional)` group (under Current Liabilities),
  debiting `received_in_account`.
  `voucher_type` derives from the received-in account type (Bank vs
  Cash). Cancel cascade in both directions reuses
  `utils.on_journal_entry_cancel` (generic over source doctype).
- **Student Fee Receipt Head** — child row holding `(head, amount)`.
- **Student Fee Refund** (submittable, `SRF-.YYYY.-`) — refund a paid
  admission fee. Mirror of Receipt with reversed JE legs: debits
  `Admission/Registration Fee (Provisional)`, credits `paid_from_account`.
  Same heads child table for itemised refunds. Soft-warns when the
  refund exceeds the student's total paid to date or when the student
  has no fee receipt on file; never hard-blocks. Orange-accented print
  format ("Admission Fee Refund Voucher"). Wired into the Backdating
  Policy as the 10th controlled doctype via `v1_3`/`v1_4` patches.
  Also carries the four read-only `income_*` tracking fields — see §8.
- **Student Fee Refund Head** — child row mirror of Student Fee
  Receipt Head: `(head, amount)`.

Receipt form behaviour (`student_fee_receipt.js`): admission_year
auto-defaulted to the current Indian FY (computed sync in JS, format
`FY YYYY-YY`); Student picker scoped to receipt's company; Fee Head
picker on each row scoped to student's course; Received In Account
picker scoped to company + Mode-of-Payment type (Bank or Cash);
switching student or company clears stale dependent fields. Inline-
create on the Student field for register-as-you-collect.

**Print Format**: green-accented receipt mirroring the Ex Student
Receipt style; itemised Fee Heads table replacing the Outstanding
Ledger block; amount-in-words; signature strip.

**Report — `Admission Fee Register`** (Script Report): flat list of
submitted receipts with KPI cards (Receipts count / Total Collected /
Distinct Students) and a bar chart of receipt count per Admission
Year when the result spans more than one year. Filters: Company,
From/To Date (defaults to current FY), Course, Admission Year, MOP.

Wired into the **Backdating Policy** as the eighth controlled
doctype; `v1_2/seed_student_fee_receipt_rule` patch adds the rule
row on already-deployed sites.

### 8. Retained Admission Fee → Income

When an admission fee is only *partly* refunded, the amount the
institution keeps stays parked in the `Admission Fee (Provisional)`
liability for that student. This books it out to income:

```
Dr  Admission/Registration Fee (Provisional) - {abbr}
Cr  Income From Admi Cancellation - {abbr}      (Income → Indirect Income)
```

- **`Student Fee Settings`** (Single, System Manager / Accounts Manager
  write, Accounts User read) — one optional field,
  `retained_fee_income_account`. Leave it blank and the account resolves
  **by per-company convention** to `Income From Admi Cancellation -
  {abbr}`, mirroring how the Admission Fee account is named. Set it only
  to override with a differently-named account.
- **`student_fee.get_retained_income_account(company)`** — override wins,
  else the convention name. Either path runs
  `_validate_income_account`: must exist, must be a ledger (non-group),
  and must belong to that company (ERPNext rejects a cross-company
  account in the JE).
- **`student_fee.book_income(refund, posting_date=None)`** (whitelisted)
  — posts the 2-line JE for the student's FULL current remaining,
  anchored to a submitted Student Fee Refund, then stamps that refund's
  `income_*` fields. Idempotent: one booking per refund.
- **"Remaining" is student-level**, computed across ALL of the student's
  submitted docs, not just the filtered window:
  `remaining = total paid − total refunded − income already booked`.
  So it stays correct regardless of the date filter and drops to zero
  once booked.
- **Cancel semantics** (`utils.py`): cancelling the **income JE** clears
  the booking *without* cancelling the refund; cancelling the **refund**
  reverses the income JE. That branch sits before the
  `custom_source_voucher` logic and cannot match a normal backend JE —
  the income JE is deliberately NOT linked back via
  `custom_source_voucher`.

**Report — `Student Fee Refund Income`** (Script Report): every submitted
refund in the window with Paid / Refunded / Remaining / income status,
KPI cards (Refunds · Total Refunded · Pending Income · Income Booked)
and a per-row **"Book as income"** button so the whole flow runs from one
screen. Pending Income is de-duplicated per student, so a student with
two refund rows is not counted twice. Balances come from
`_bulk_balances` — one grouped query per leg, not a query per row.
Filters: Company, From/To Date, Course, Status (All / Pending / Booked).

---
### 9. Dux Trial Balance

Replaces ERPNext's **Trial Balance** and **Trial Balance for Party** —
two disconnected reports that cannot see each other. This is one engine
(`report/dux_trial_balance/`) parameterised by a grouping, with a custom
Page (`/app/dux-trial-balance`) as the primary surface. The Page calls the
SAME `execute()`; it never recomputes, so the two cannot disagree.

Four views, one GL slice at different resolutions:

| View | Rows are |
|---|---|
| By Account | CoA tree, child values rolled into groups |
| By Party | every party, **all party types at once** |
| Account → Party | control accounts expanded into their parties, plus an explicit **Unattributed** row |
| By Company | one row per company, for trusts and comparison |

**Things that will bite you if you do not know them:**

- **No fiscal-year clamp.** ERPNext's `validate_filters` silently rewrites
  an out-of-year range, so a period spanning two fiscal years is not
  expressible there. Here Fiscal Year only fills the dates. This site has
  *overlapping* fiscal years (`2026-2027` Apr–Mar and `2026-2028`
  Jan–Dec), so never derive "the" fiscal year from a date.
- **P&L opening resets at the fiscal-year boundary**, and the amount
  removed is surfaced as a computed *Accumulated Loss/Profit b/f* row.
  Without it this ledger reads ~68 crore out of balance — which is
  exactly what ERPNext's own TB shows, unexplained. No Period Closing
  Voucher has ever been run here, so the reset happens at query time.
- **Cancelled entries: `is_cancelled = 0` alone is sufficient.** Measured
  across 5,088,888 GL rows — zero live rows have a cancelled parent
  JE/PE. The reversal carries the ORIGINAL posting date, so cancelling a
  back-dated voucher today never leaks into today.
- **One wide `company IN (...)` GROUP BY is pathological here.** 69
  companies took 38–77s and blew gunicorn's 120s worker timeout, which
  surfaced as a bare "Internal Server Error" with nothing in the Error
  Log. Query **per company** and accumulate — the arithmetic is
  identical. This lesson has paid out three times now.
- **Party attribution is largely absent.** ~₹88.8M sits on
  Receivable/Payable accounts with no party at all, 93–100% of rows on
  some companies. The Unattributed row is permanent furniture, not an
  error state.

**Trusts** use ERPNext's **native** company nested set (`parent_company` /
`is_group` / `lft` / `rgt`); selecting a group company expands to its
subtree via `get_subsidiary_companies`. Do not build a parallel
hierarchy — production already maintains this one.

**Two tiers.** A few companies → live GL. A trust or many companies →
`Dux TB Period Balance`, rebuilt nightly, because live is not possible at
that width. The report **always states which source it used and when the
aggregate was built**.

**Roles** (seeded by `v1_5`): `Dux Trial Balance` reads;
`Dux Trial Balance Manager` also rebuilds the aggregate. Gating the
Report and Page records only hides it from the menu, so every whitelisted
endpoint calls `require_access()` and `tb_aggregate.rebuild` calls
`require_manager()`. User-Permission company scoping applies on top.

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
- **Ledgers must tie**: every ledger surface routes its opening/closing
  through `_taccount_summary`, so Total Debit == Total Credit. The Day
  Book is the deliberate exception — one-sided per voucher, totals do
  not tie
- **Retained-fee income is one booking per refund**, sized to the
  student-level remaining, and is reversible from either end

---

## Pending Work

- [ ] Smoke tests for Formatted TB and Backdating (planned in
      `formatted_reports/PLAN.md` §5.3 — needs the marker assertion
      against the built bundle)
- [ ] Eventual merge of accumulated feature branches back into
      `version-1` so main reflects production reality
- [ ] Tag `formatted-tb-v1.0.0` for a clean rollback point on the
      formatted-TB feature

> **Note:** this repository is public. Keep credentials, tokens and
> internal hostnames out of committed files — including this one.

## Recently Completed

- [x] **Dux Trial Balance** — one engine, four groupings, replacing
      ERPNext's two disconnected trial balances. Free date range,
      native trust roll-up, monthly aggregate for wide multi-company
      runs, period/company comparison, inline party expansion on
      control accounts, drill-through into the Dux ledgers in a new
      tab, formatted xlsx export, and two dedicated roles. Validated
      against ERPNext's own Trial Balance: 113 accounts, zero
      differences on all six value columns, 0.45s against its 48.79s
- [x] **Party surfaced in ledger Particulars** — rows with no party of
      their own show the voucher's party, so a TDS ledger names the
      deductee instead of the expense head. Display-time only,
      retroactive
- [x] **Day Book one-sided Dr/Cr** — Tally shows each voucher's value in
      a single column by nature; per-row dates; responsive breakpoints
      and wrapping remark strings across all five report pages
- [x] **Party Trial Balance page** — per-party Opening / Debit / Credit /
      Closing matching ERPNext's column layout, party search, single
      Party column, and click-through into that party's Party Ledger
- [x] **Strict T-account layout** — opening on its natural side, closing
      carried down as a balancing contra, footer ties Debit == Credit,
      via one shared `_taccount_summary` helper
- [x] **"Various" drill-down** — per-row counter-account breakdown on
      screen, in print and in Excel, from one batched GL query
- [x] **Retained admission fee → income** — Student Fee Settings single
      doctype, `book_income` + account resolver, `income_*` fields on
      Student Fee Refund, two-way cancel handling, and the Student Fee
      Refund Income report with a per-row booking action
- [x] **Student Fee Refund** — submittable doctype mirroring Student
      Fee Receipt with reversed JE legs (Dr Admission/Registration Fee
      (Provisional), Cr Bank/Cash) and the same `heads` child table
      for itemised refunds. Soft-warns when the refund exceeds the
      student's total paid to date (via `get_student_paid_summary`)
      or when the student has no fee receipt on file. Never hard-
      blocks. Orange-accented print format ("Admission Fee Refund
      Voucher"). Wired into the Backdating Policy as the 10th
      controlled doctype via `v1_4` patch. Reuses
      `get_admission_fee_account`, `_validate_bank_cash_account`,
      `_submit_doc`, `_safe_cancel`, and the existing generic
      `on_journal_entry_cancel` cascade hook
- [x] **Ex Student Refund** — submittable doctype mirroring Ex Student
      Receipt with reversed JE legs (Dr Receivable, Cr Bank/Cash) and
      a ledger entry on the debit side. Soft-warns when paying a Dr-
      balance student or when refund exceeds available Cr; never hard-
      blocks. Orange-accented print format. Wired into the Backdating
      Policy as the 9th controlled doctype via `v1_3` patch. Reuses
      `_get_ex_student_accounts`, `_validate_bank_cash_account`,
      `_submit_doc`, `_safe_cancel`, and the existing generic
      `on_journal_entry_cancel` cascade hook
- [x] **Student Ledger page** — unified ex + new student statement,
      reusing the ledger renderer and workbook builder verbatim
- [x] **New Student Admission Receipts** — Course + Course Fee Head +
      Student + Student Fee Receipt + child table; receipt posts a
      single 2-line JE; polished print format; Admission Fee Register
      report with KPI cards; 32 new unit tests across the masters and
      receipt validation; wired into the Backdating Policy as the 8th
      controlled doctype via `v1_2` patch
- [x] **Backdating Policy** — Single doctype + 3 child tables + seed
      patch + backfill patch + per-rule `date_field` override; 27 unit
      tests; wired into 10 controlled doctypes via `doc_events`
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
# On the target server — pick up changes from a branch
cd <bench>/apps/dux_voucher
git pull origin <branch>

cd <bench>
bench --site <site> migrate      # only when doctypes / patches change
bench --site <site> clear-cache
bench build --app dux_voucher    # only when JS / CSS bundles change

# IMPORTANT: bench restart is a NO-OP on the dev host — that account
# cannot sudo supervisorctl. Always reload via SIGHUP:
pkill -HUP -f "gunicorn.*frappe"
```

Browser hard-refresh (Ctrl+Shift+R) when a JS bundle hash changes.

Frappe **Pages** (`page/*.js`) load from disk per request — no build and
no migrate needed, a hard refresh is enough.

**Production flow:** edits land on dev first → `git push origin
<branch>` → on production `git pull` + the migrate/build/HUP trio above.
No `bench restart` anywhere.

### Dev-server gotcha — reports disappearing

The dev bench carries 30+ apps and something in its deploy cycle
periodically deletes standard `Report` records; with `developer_mode=1`
that also removes the report folder from disk. Symptom: `git status` in
the app shows report files as deleted, and the report 404s in Desk.
Recovery is non-destructive:

```bash
cd <bench>/apps/dux_voucher
git checkout -- dux_voucher/dux_voucher/report/
bench --site <site> migrate      # re-imports the standard Report records
bench --site <site> clear-cache
```

Production has never been affected.

---

## Gotchas learned the hard way

- **`frappe.db.get_value` rejects SQL aggregates as column strings** —
  `["SUM(x) AS y"]` throws "SQL functions are not allowed as strings in
  SELECT". Use `frappe.db.sql` for aggregates.
- **JS `validate(frm)` runs BEFORE the server computes read-only fields**
  — a controller-computed field like `total_amount` is still `0` in the
  client `validate`. Sum the live grid instead:
  `(frm.doc.heads || []).reduce((s, r) => s + flt(r.amount), 0)`.
- **Amending a cancelled submittable → "Cannot link cancelled document"**
  — `Document.insert` runs `_validate_links()` *before* `before_insert`,
  so cleanup there is too late. Override `insert()` and clear
  `backend_je` / `is_posted` when `amended_from` is set. Already applied
  to PV, RV, Student Fee Receipt, Student Fee Refund, Ex Student Refund.
- **A corrupted DocType JSON can hide for weeks** —
  `student_fee_receipt.json` was once overwritten with Print Format
  content. The site kept working (the DocType was already in the DB) but
  `bench migrate` silently skipped it, so JSON edits stopped applying.
  Sanity-check that a doctype JSON says `"doctype": "DocType"` before
  assuming a migrate no-op is fine.
- **Never put two git worktrees on the same branch.** A branch ref is
  shared across worktrees, so when one session commits, the ref advances
  underneath the other while its files stay old — and git reads that gap
  as "delete everything new". Work in the main checkout, or let the tool
  create a worktree on its own scratch branch.

---

## Source layout cheatsheet

Notable cross-cutting files when you need to find something fast:

| Concern | File |
|---|---|
| `doc_events`, `app_include_js`, fixtures, permissions | `dux_voucher/hooks.py` |
| Cancel-cascade between PE/JE and parent vouchers | `dux_voucher/dux_voucher/utils.py` |
| Posting-date enforcement | `dux_voucher/dux_voucher/api/backdating.py` |
| Admission-fee + retained-income account resolvers, `book_income` | `dux_voucher/dux_voucher/api/student_fee.py` |
| Page reports + xlsx exports | `dux_voucher/dux_voucher/api/reports_api.py`, `reports_export.py` |
| T-account opening/closing maths (all ledger surfaces) | `reports_api.py` → `_taccount_summary` |
| Day Book particulars resolution | `reports_api.py` → `_build_day_book_particulars_map` |
| Party Trial Balance page | `dux_voucher/dux_voucher/page/dux_party_trial_balance/` |
| Party Trial Balance backend | `reports_api.py` → `get_party_trial_balance` |
| Student Ledger page (ex + new student) | `dux_voucher/dux_voucher/page/dux_student_ledger/` |
| Student Ledger backend (`get_student_ledger`, `search_students`) | `dux_voucher/dux_voucher/api/reports_api.py` |
| Formatted TB workbook builder | `dux_voucher/formatted_reports/trial_balance/builder.py` |
| Site-wide settings doctypes | `doctype/dux_backdating_settings/`, `doctype/student_fee_settings/` |
| Student Fee Receipt controller + JE posting | `dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py` |
| Student Fee Receipt form behaviour (picker filters, FY default) | `dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.js` |
| Student Fee Refund controller + income fields | `dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.py` |
| Admission Fee Register report | `dux_voucher/dux_voucher/report/admission_fee_register/` |
| Student Fee Refund Income report | `dux_voucher/dux_voucher/report/student_fee_refund_income/` |
| Trial Balance engine (all four views) | `dux_voucher/dux_voucher/report/dux_trial_balance/dux_trial_balance.py` |
| Trial Balance page (the primary UI) | `dux_voucher/dux_voucher/page/dux_trial_balance/dux_trial_balance.js` |
| Trial Balance API + role guards | `dux_voucher/dux_voucher/api/trial_balance.py` |
| TB monthly aggregate + nightly job | `dux_voucher/dux_voucher/api/tb_aggregate.py` |
| TB Excel export | `reports_export.py` → `export_trial_balance_xlsx` |
| Voucher controllers | `dux_voucher/dux_voucher/doctype/{payment,receipt}_voucher/` |
| Ex-student lifecycle | `dux_voucher/dux_voucher/doctype/ex_student*/` |

For exact source, browse on GitHub or `git ls-files` on the server.
