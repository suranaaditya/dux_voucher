# Raisoni Group — Project Dashboard: Research & Plan

Goal: make **Project** a reliable dimension across the whole spend chain, then
build a dashboard on it. Plus a deliberately simple "create a project" screen.

Everything below is traced to ERPNext `version-16` source (matching
ERPNext 16.10.0 / Frappe 16.12.0) or read first-hand from our own apps.
Claims that could not be confirmed are marked NEEDS-VERIFICATION.

---

## 1. Scope split

| Where | What |
|---|---|
| **This session** (`dux_voucher`) | Payment Voucher / Receipt Voucher project fix · Project dashboard · New Project screen |
| **WO session** (`dux_civil_works`) | Purchase Invoice ← Work Order Contract link · Material Request project |

The prompt for the WO session is in §7.

Confirmed with the client: **one invoice never covers two Work Orders; one WO
can have many POs.** So the WO link on Purchase Invoice is a single header
field, not a table.

---

## 2. The mechanism — how a project reaches the books

This is the single most useful fact, and it makes most of the work small.

`erpnext/accounts/services/base_gl_composer.py::get_gl_dict()` seeds every GL
row with:

```python
"project": doc.get("project"),
```

**Any document with a parent-level `project` field stamps it onto every GL
Entry it creates — automatically.** No custom field, no dimension setup.

Two riders:

- Journal Entry additionally sets `project` **per account row**, so a JE can
  split one voucher across several projects.
- For true Accounting Dimensions (not Project), an item-level value overrides
  the parent. Project is special — see below.

**Project is a built-in pseudo-dimension, not an Accounting Dimension record.**
`AccountingDimension.validate_doctype()` explicitly throws *"Not allowed to
create accounting dimension for Project"*. Project and Cost Center are
hardcoded everywhere the dimension machinery runs. Do **not** try to create an
Accounting Dimension for Project — it is already one.

**`accounting_dimension_doctypes` is a hook**, not a fixed list — so
`dux_voucher` can register Payment Voucher / Receipt Voucher from its own
`hooks.py` and every dimension the group ever creates flows into them
automatically. Worth doing once, cheap, future-proof.

---

## 3. Where `project` stands today

### 3a. ERPNext natives (version-16, verified field-by-field)

| Doctype | Parent | Item/child |
|---|---|---|
| Purchase Order | ✅ | ✅ |
| Purchase Receipt | ✅ | ✅ |
| Purchase Invoice | ✅ (`allow_on_submit`) | ✅ (`allow_on_submit`, `search_index`) |
| **Material Request** | ❌ **none** | ✅ |
| Work Order (manufacturing) | ✅ | — |
| Stock Entry | ✅ | ✅ |
| Journal Entry | — | ✅ per account row |
| **Payment Entry** | ✅ **(`allow_on_submit`)** | — |
| GL Entry | ✅ | — |

`get_mapped_doc` copies same-named fields, so project rides
MR → PO → PR → PI **at item level** with no code from us.

### 3b. Our apps

| Document | project? | Reaches GL? |
|---|---|---|
| Work Order Contract | ✅ but **optional** (`reqd=0`) | n/a — posts no GL |
| Work Order RA Bill | ✅ read-only, `fetch_from: civil_work_order.project` | n/a |
| Payment Voucher — Head-wise | ✅ | ✅ works today |
| Payment Voucher — Party + Head | ✅ | ✅ works today |
| **Payment Voucher — Party-wise** | field shown | ❌ **dropped** |
| **Payment Voucher — Contra** | field shown | ❌ **dropped** |
| **Receipt Voucher — Party-wise** | field shown | ❌ **dropped** |

The three ❌ rows all create **Payment Entries**. The field is visible in every
mode with no `depends_on`, so an operator fills in Project on a party-wise
vendor payment, gets no error, and the value never leaves the voucher.

**This is the worst kind of gap — it looks like it works.**

---

## 4. Decisions needed before building

### 4a. `project_name` is globally unique — BLOCKER at 69 companies

`Project.project_name` carries `unique=1` with **no company qualifier**. Two
colleges cannot both create *"Library Renovation"* or *"Hostel Block A"* — the
second insert fails outright.

Options:

1. **Naming convention** — prefix the institute: `GHRCE — Hostel Block A`.
   Zero code, ugly in lists, relies on discipline.
2. **Auto-prefix on the create screen** — our screen composes
   `{abbr} — {name}` behind the scenes; the user types only the plain name.
   Cheap, invisible, consistent. **Recommended.**
3. Drop the unique constraint via Property Setter — possible, but it fights
   ERPNext and risks genuine duplicates.

### 4b. The dashboard must read GL, not Project's own numbers

Project's costing fields look tempting and are the wrong source:

- `total_purchase_cost` reads **`Purchase Invoice Item.project` only.** Purchase
  Orders and Purchase Receipts contribute **nothing**.
- It is maintained by **incremental delta arithmetic** on PI submit/cancel
  (read value, add or subtract) via `db_update()`, bypassing validate. Amendments,
  direct edits or a failed job leave it permanently skewed.
- The only from-scratch reconcile job, `update_project_sales_billing`,
  **early-returns** when `Selling Settings.sales_update_frequency == 'Each
  Transaction'` — the common configuration. On such a site nothing ever
  recomputes from scratch.
- **Nothing on Project rolls up GL Entry at all.** Every field reads one
  specific source doctype. Payments made through our Payment Voucher would
  never appear.

**Decision: the dashboard computes from `tabGL Entry.project`.** That is the one
place every document type lands with project already populated. Project's own
fields may be *displayed* for reference, never used as the number of record.

### 4c. Work Order Contract's project is optional

If the dashboard is anchored on WO → project, an optional field means holes.
Recommend making it required on Work Order Contract, or defaulting it.
(WO session — see §7.)

---

## 5. Work in this session (`dux_voucher`)

### 5a. Close the Payment Entry gap — small and high value

Set `pe.project` in the three PE-building methods:

- `payment_voucher.py::_create_party_payment_entries` (~:223)
- `payment_voucher.py::_create_contra_payment_entry` (~:308)
- `receipt_voucher.py::_create_party_receipt_entries` (~:189)

Payment Entry has a native parent `project`, and `get_gl_dict` carries it to
GL — so this is genuinely ~3 lines plus tests. No custom field.

Party-wise creates **one PE per party row**, and `PV Party Row` has **no**
project field (six fields only: party, party_type, party_name, amount,
current_balance, balance_type). So every PE from one voucher takes the
**header** project. If per-row projects are ever needed on party-wise, that is a
separate change — flag, don't assume.

Contra is an Internal Transfer between two bank accounts. Header project is the
only sensible source there.

### 5b. Register our vouchers as dimension-aware (optional, cheap)

Add to `dux_voucher/hooks.py`:

```
accounting_dimension_doctypes = ["Payment Voucher", "Receipt Voucher",
                                 "PV Account Row", "RV Account Row", ...]
```

Then call `create_accounting_dimensions_for_doctype()` once per doctype in a
patch to retrofit dimensions that already exist. Note the injection runs as a
**long-queue background job** — fields appear after the job, not on save.

### 5c. Project dashboard

See §8.

### 5d. New Project screen

See §9.

---

## 6. What we deliberately do NOT build

- **Project's costing rollups** — already there; we just don't trust them as
  the source of truth.
- **Project budgets.** v16 ships a new engine
  (`erpnext/controllers/budget_controller.py::BudgetValidation`) that fires from
  `make_gl_entries()` and keys on (dimension, value, account) with **project
  hardcoded**. So Stop/Warn on project budgets works against GL on any voucher
  — including ours, once project reaches GL. **Caveat:** `Budget.validate_account()`
  only accepts accounts with `report_type == 'Profit and Loss'`, so a capital
  project posting to CWIP (balance sheet) **cannot** be budgeted natively.
- **Budget Variance Report** — already supports Project as `budget_against`.
- **Profitability Analysis** — the only native report that *pivots by* project.
  General Ledger, Trial Balance and P&L accept project only as a **filter**, not
  a grouping.
- **The Projects workspace, Gantt, Kanban, Task, Timesheet** — all native.
- `project.js` already gives Create → PO / PR / PI from a Project form,
  pre-stamping project. Free.

---

## 7. Prompt for the WO session

> Paste this into the `dux_civil_work_order` session.

```
Two changes, both about making Project a reliable dimension so a group-wide
project dashboard can be built. Do NOT build any dashboard here.

CONTEXT ESTABLISHED BY RESEARCH (trust these, they are traced to ERPNext
version-16 source; re-verify anything you intend to rely on):

- base_gl_composer.get_gl_dict() seeds every GL row with
  "project": doc.get("project"). So ANY doctype with a parent-level `project`
  stamps it onto its GL Entries automatically. No custom field needed.
- Purchase Invoice has `project` at BOTH parent and item level, both with
  allow_on_submit=1.
- CRITICAL: ERPNext computes Project.total_purchase_cost from
  `Purchase Invoice Item.project` — the ITEM field, not the header. A header-only
  project leaves that rollup at zero.
- Material Request has `project` at ITEM level ONLY. The parent has no project
  and no cost_center, and MR is not in accounting_dimension_doctypes, so it will
  never acquire one automatically.
- get_mapped_doc copies same-named fields, so item-level project rides
  MR -> PO -> PR -> PI with no code.
- Stock Entry's before_validate is the reference cascade pattern:
  if self.project: for item in self.items: if not item.project: item.project = self.project

CHANGE 1 — Purchase Invoice gets a Work Order Contract link.

Business rule confirmed with the client: one invoice never covers two Work
Orders; one Work Order can have many Purchase Orders. So this is a single
header Link, not a table.

- Add a custom field on Purchase Invoice (header): Link -> Work Order Contract.
  Ship it as a fixture from dux_civil_works, which owns that doctype.
- Filter the picker by the invoice's company AND supplier (Work Order Contract
  carries both).
- On validate: if the WO is set AND `project` is empty, fill project from the
  WO's project. NEVER overwrite a project the user typed - manual entry wins.
  Do this server-side so API and import paths behave the same, and mirror it in
  the client script for immediate feedback.
- Validate that the WO's company matches the invoice's company; throw if not.
- THEN cascade: on before_validate, copy the header project into every item row
  whose project is blank. Without this, Project.total_purchase_cost stays zero.
- Do not make project read-only. It must remain settable independently on
  invoices that have no Work Order.

CHANGE 2 — Material Request project.

- Add a parent-level `project` custom field on Material Request.
- Cascade it into Material Request Item rows that have a blank project, using
  the Stock Entry before_validate pattern above.
- Do not touch the existing item-level field; it stays authoritative, the header
  is just a convenience that fills blanks.

ALSO CONSIDER (raise with the user, do not just do it):
- Work Order Contract.project is currently OPTIONAL (reqd=0). A dashboard
  anchored on WO -> project will have holes. Ask whether it should be required.

Follow this app's established workflow: create artifacts through
`bench --site <site> console` scripts, never hand-write JSON, edit generated
controllers freely, verify from console rather than by clicking. Commit locally,
one logical change each, do not push without asking.
```

---

## 8. Dashboard design

**Source of truth: `tabGL Entry`, filtered on `project`.** Reuse the Dux Trial
Balance engine — it already has a working project WHERE clause, is parameterised
by grouping, and already loops **per company** because a wide
`company IN (...)` GROUP BY blows the 120s gunicorn timeout at 69 companies.

Delivered as a Frappe **Page**, matching the seven existing Dux pages, rather
than a Workspace — same look, no build step, no migrate.

### Layout

**Filters:** Company (multi, respecting User Permissions) · Project (multi) ·
Date range · Status.

**KPI row** — computed from GL:
Committed (PO not yet invoiced) · Invoiced (PI) · Paid (PE/JE against the
project) · Outstanding · Budget vs Actual where a project budget exists.

**Spend by project** — the main table. One row per project: company, status,
budget, committed, invoiced, paid, balance, % of budget. Click through to the
GL rows behind any number.

**Spend by head within a project** — the drill-down: account-wise breakdown,
which is what the Trial Balance engine already produces.

**Pipeline strip** — counts and values by stage: Work Orders → POs → Receipts →
Invoices → Payments. Shows where each project is stuck.

**Recent activity** — last N documents touching the project, all types.

### Honest limits to state on the page

- Anything booked without a project is invisible here. Show an
  **"Unattributed"** row with the total, exactly as the Trial Balance does — it
  is the number that tells you how much of the chain is leaking.
- Committed-but-not-invoiced comes from PO, which does **not** hit GL. That
  column is document-derived, not GL-derived, and must be labelled as such.

---

## 9. New Project screen

The client asked for something easy and good-looking, without unnecessary
options. ERPNext's Project form has **59 fields across 5 tabs**. Almost all of
it is irrelevant to a construction project at an institute.

**Only three fields are genuinely mandatory:** `naming_series`, `project_name`,
`company`.

### Proposed screen — 6 fields, one card

| Field | Why |
|---|---|
| Institute (Company) | Mandatory. Drives the name prefix and every filter |
| Project name | Mandatory. Plain name — we prefix the institute behind the scenes (§4a) |
| Project type | Optional but useful for grouping the dashboard |
| Expected start / end | Two dates, for the timeline strip |
| Estimated cost | Maps to `estimated_costing` — the only budget-like native field |
| Status | Defaults to Open |

Everything else — Tasks, Timesheets, progress collection, email reminders,
customer/sales order, users, notes — stays hidden at defaults.

### Two gotchas to handle

**Status gets hijacked.** On every save, `update_percent_complete()` forces
`status` to Open or Completed from task-completion maths, unless the project is
Cancelled/On hold or `percent_complete_method == 'Manual'`. For construction
projects that do not use ERPNext Tasks, **set `percent_complete_method = Manual`
on create** — otherwise status and % never behave sensibly.

**Naming.** The document name is `PROJ-####` from a single global series;
`project_name` is only the title. Across 69 companies, `PROJ-0042` carries no
institute signal. Consider a per-company series, or rely on the prefixed name.

Frappe's Quick Entry is already enabled on Project (`quick_entry: 1`), but only
`project_template` is flagged for it — so out of the box the quick dialog shows
naming_series + project_name + company and little else. Our screen is a
deliberate replacement, not a fight with it.

---

## 10. Open questions

1. **§4a** — auto-prefix the institute onto project names? (Recommended.)
2. **§4c** — make Work Order Contract's project required?
3. Do any projects span more than one institute, or is one project always one
   company?
4. Should the dashboard be group-wide (all 69) or per-institute by default?
   The per-company query loop matters at trust level.
