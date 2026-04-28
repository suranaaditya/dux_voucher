# Formatted Trial Balance — Handoff to Claude Code

> **Read this file first, in full, before writing any code.** It contains the
> locked design contract, architecture decisions, and reference implementation
> from a prior planning session in claude.ai. Your job is to translate this
> into a working module inside the `dux_voucher` Frappe app.

---

## 0. Branch & commit hygiene

The current Claude Code session is on `feature/ex-student-module`. **Before
writing any code for this work**, branch off:

```bash
cd ~/dev/dux_voucher  # or wherever the local clone is
git checkout -b feature/formatted-tb-export
```

This work is unrelated to ex-student-module. Mixing them blocks PR review
and clean rollback.

Commit cadence: **small focused commits, one per logical step**. Stop and
ask before merging. Tag `formatted-tb-v1` only after end-to-end validation
on `erp.jewonline.in` passes.

---

## 1. Goal

When a user runs the standard ERPNext Trial Balance report and clicks a new
**"Download Formatted TB"** button, the system generates a polished
multi-sheet `.xlsx` file matching the locked design contract in §3, using
the same data the standard report produced.

The deliverable is one Frappe app module — `dux_voucher.formatted_reports`
— with one report transformer (`trial_balance`). Future formatted reports
(BS, P&L, GL) will be added as siblings under the same module.

---

## 2. Environment

- **Dev server**: `erp.jewonline.in`, Frappe v16.12.0, bench at
  `frappe@<dev_ip>:~/frappe-bench`
- **Test companies on dev**: `JEWIPL` (Jain Engineering Works (India)
  Private Limited) and `DD` (Dux Digitech) — both INR
- **App**: `dux_voucher` (existing). New module added inside it.
- **Publisher convention**: Dux Digitech, MIT
- **Target Frappe versions**: 15.x and 16.x (at minimum, must work on 16.12)

---

## 3. Locked design contract (v5)

Two sheets, one file. Both reference the same numbers via formulas — they
cannot drift out of sync.

### 3.1 Sheet 1 — `Summary` (opens by default)

**Title block** (rows 2–4):
- Row 2: Company name in slate `#2C3E50`, bold, 14pt, left-aligned
- Row 3: `Trial Balance  ·  FY YYYY-YYYY  (DD MMM YYYY – DD MMM YYYY)` in
  slate-lite `#7F8C9A`, 10pt
- Row 4: medium-weight slate accent rule (border-bottom across B:E)

**Tie status banner** (rows 6–7), spanning B6:E7:
- Out of balance: light-red wash `#FCEAEA`, red border `#F0B5B5`,
  `⚠   TRIAL BALANCE OUT OF BALANCE` headline in muted red `#B91C1C`
  (13pt bold), `Difference  ·  Closing (Dr) − Closing (Cr)` sub-text on
  row 7 with the difference amount in column E
- Tied: light-green wash `#E8F5EE`, green border `#A7D5B8`,
  `✓   TRIAL BALANCE TIED` headline in muted green `#047857`,
  `Closing (Dr) equals Closing (Cr)` sub-text
- Banner styling is computed at file-generation time based on actual
  Closing Dr − Closing Cr from the Detail sheet's Total row.

**Closing Position table** (starts ~row 10):
- Section header "Closing Position" in slate bold 11pt
- Table header row with slate-tint fill `#E1E7EF`, slate text, hairline below
- Four rows: Assets, Liabilities, Income, Expenses (in that order)
- Each row's name is a hyperlink to the corresponding top-group row on Detail
- Closing (Dr) and Closing (Cr) columns use IF formulas
  (`=IF(Detail!F<r>=0,"—",Detail!F<r>)`) to render zero as em-dash
- Missing top groups (e.g. no Income on JEWIPL): name in slate-lite italic,
  both columns show em-dash directly (no hyperlink)
- Hairline `#D6DBE0` between every data row

**Period Activity table** (~3 rows below Closing Position):
- Same section header + table header treatment
- Three rows: Total Debits, Total Credits, Net (Dr − Cr)
- Total Debits/Credits rows: regular font, slate values, hairline below
- **Net row**: bold, in the banner colour (red if out of balance, green
  if tied), with same wash background as banner; top thin border to mark
  it as the calculated total

**Footer**: `View full account-level detail  →` hyperlink to
`#'Detail'!A1`, in link blue `#0563C1`, italic 10pt

**Page setup**: portrait, A4, fitToWidth=1, no gridlines

### 3.2 Sheet 2 — `Detail`

**Title block** (rows 1–3): same as Summary's title, plus a
`←  Back to Summary` hyperlink in column G of row 2

**Header row** (row 4): bold slate text on white, hairline below.
Columns: Account, Opening (Dr), Opening (Cr), Debit, Credit,
Closing (Dr), Closing (Cr)

**Data rows** (row 5 onwards) styled by hierarchy:
- **Top groups** (level 0): slate-tint fill `#E1E7EF`, slate text, bold,
  11pt, row height 22pt
- **Sub-groups** (level 1, e.g. Current Assets): soft gray fill `#F2F3F5`,
  bold black, 10pt, row height 19pt
- **Deeper groups** (level 2+ that have children): bold only, no fill, 10pt
- **Leaves**: regular weight, dark gray text `#3D3D3D`, 10pt
- **Hairline** `#D6DBE0` between every data row, NO vertical borders
- **Real Excel indent** via `cell.alignment.indent` matching the
  hierarchy level — NOT leading spaces in the string
- Strip the company suffix (e.g. `" - JEWIPL"`) from every account name

**A row is "is_group"** iff the next visible row sits at a deeper indent.

**Total row**: bold slate text 11pt, top medium border, bottom double border

**Tie-check row** (2 rows below Total):
- Label "Check  ·  Closing (Dr) − Closing (Cr)" in italic slate-lite 9pt
- Difference formula `=F<total_r>-G<total_r>` in column G,
  italic muted-red 9pt bold

**Sign-off footer** (5 rows below tie-check):
- Three labels: "Prepared by" (col A), "Reviewed by" (col D),
  "Date" (col F), in slate-lite 9pt
- Hairline below each label for handwritten sign-off, merged across
  appropriate column ranges

**Outline grouping** — only TWO levels (collapse-aware):
- Top-group rows: `outline_level = 0`
- All other rows: `outline_level = 1`
- `summaryBelow = False`, `summaryRight = False`
- Default state: fully expanded

**Indian number format**:
```
[>=10000000]##\,##\,##\,##0.00;[>=100000]##\,##\,##0.00;##,##0.00
```
Cells with value 0 are written as `None` (blank) for readability.

**Page setup**: landscape, A4, fitToWidth=1, fitToHeight=0,
fitToPage=True, freeze at B5, header rows 1:4 repeat on print

### 3.3 What v5 explicitly does NOT contain

- No chart (removed at user's request)
- No vertical borders anywhere
- No fills on leaf rows
- No cell-level grid borders
- No account code column, no period comparator, no materiality marker,
  no decimal toggle, no notes column. (Those are deferred to a future
  iteration.)

---

## 4. Architecture

### 4.1 Module layout

Inside `dux_voucher/dux_voucher/`:

```
formatted_reports/
├── __init__.py
├── PLAN.md                      # this file (move it here)
├── trial_balance/
│   ├── __init__.py
│   ├── api.py                   # whitelisted entry point
│   ├── builder.py               # the build_v5 logic, refactored
│   ├── client_script.py         # Frappe Client Script DocType creator
│   └── tests/
│       ├── __init__.py
│       ├── fixtures/
│       │   └── jewipl_tb_sample.xlsx     # the sample source file
│       └── test_builder.py
└── README.md                    # short doc for whoever opens the repo next
```

### 4.2 hooks.py additions

In `dux_voucher/hooks.py`, append:

```python
doctype_js = {
    **(doctype_js if "doctype_js" in dir() else {}),
    # If "Trial Balance" appears, override its onload — but client_script
    # below registers itself as a Custom Script DocType, which is the more
    # upgrade-safe path. Use ONE of these two mechanisms, not both.
}

# Run installer to create/update the Custom Script for Trial Balance
after_install = ["dux_voucher.formatted_reports.trial_balance.client_script.ensure_custom_script"]
after_migrate = ["dux_voucher.formatted_reports.trial_balance.client_script.ensure_custom_script"]
```

### 4.3 Server method signature

```python
# dux_voucher/formatted_reports/trial_balance/api.py
import frappe, json, os
from frappe.utils.file_manager import save_file
from .builder import build_formatted_tb

@frappe.whitelist()
def export_formatted_tb(filters):
    """Generate formatted Trial Balance and return a private File URL.

    Calls ERPNext's standard Trial Balance execute() to obtain the data,
    then applies dux_voucher's v5 formatting via openpyxl. Never re-
    implements accounting logic.
    """
    if isinstance(filters, str):
        filters = json.loads(filters)

    # Reuse standard TB report
    from erpnext.accounts.report.trial_balance.trial_balance import execute
    columns, rows = execute(filters)

    # Build formatted file in memory
    xlsx_bytes, filename = build_formatted_tb(filters, columns, rows)

    # Save as private File attached to the current user
    file_doc = save_file(
        filename,
        xlsx_bytes,
        dt=None, dn=None,            # not attached to a specific document
        is_private=1,
    )
    return {"file_url": file_doc.file_url, "file_name": file_doc.file_name}
```

### 4.4 Client script

Two mechanisms exist; **use the Custom Script DocType approach** for upgrade
safety:

```python
# dux_voucher/formatted_reports/trial_balance/client_script.py
import frappe

CLIENT_SCRIPT_NAME = "Trial Balance — Formatted Export Button"
SCRIPT = """
frappe.query_reports["Trial Balance"] = frappe.query_reports["Trial Balance"] || {};

const _orig_onload = frappe.query_reports["Trial Balance"].onload;
frappe.query_reports["Trial Balance"].onload = function (report) {
    if (typeof _orig_onload === "function") _orig_onload.call(this, report);

    report.page.add_inner_button(__("Download Formatted TB"), () => {
        const filters = report.get_values();
        frappe.call({
            method: "dux_voucher.formatted_reports.trial_balance.api.export_formatted_tb",
            args: { filters },
            freeze: true,
            freeze_message: __("Generating formatted Trial Balance..."),
            callback: (r) => {
                if (r.message && r.message.file_url) {
                    window.open(r.message.file_url, "_blank");
                }
            },
        });
    }, __("Export"));
};
"""

def ensure_custom_script():
    """Idempotent — safe to run on every after_migrate."""
    name = frappe.db.get_value(
        "Client Script",
        {"dt": "Trial Balance", "name": CLIENT_SCRIPT_NAME},
        "name",
    )
    if name:
        doc = frappe.get_doc("Client Script", name)
        doc.script = SCRIPT
        doc.enabled = 1
        doc.save(ignore_permissions=True)
    else:
        frappe.get_doc({
            "doctype": "Client Script",
            "name": CLIENT_SCRIPT_NAME,
            "dt": "Trial Balance",
            "view": "Report",
            "script": SCRIPT,
            "enabled": 1,
        }).insert(ignore_permissions=True)
    frappe.db.commit()
```

**Important**: Frappe's `Client Script` DocType for Reports requires `view`
to be `"Report"`. Verify on dev server with:

```bash
bench --site erp.jewonline.in execute \
  "frappe.get_meta('Client Script').get_field('view').options"
```

Adjust if the DocType structure differs in 16.12.

### 4.5 Builder — adapt the reference implementation

The reference implementation `build_v5.py` (from the planning chat) reads
the standard TB Excel export and produces the v5 file. **In the module,
you will receive `columns` and `rows` as Python data structures from
ERPNext's `execute()` — not as an Excel file.** The builder needs to
operate on these in-memory structures.

Key transformations in `builder.py`:

1. **`columns` from execute()** is a list of column dicts. Find the right
   one by `fieldname`: `account`, `opening_debit`, `opening_credit`,
   `debit`, `credit`, `closing_debit`, `closing_credit`. **Look up by
   name, not by index.**

2. **`rows` from execute()** is a list of dicts (or D-objects). Each row
   has an `account` field whose VALUE is the account name with **leading
   spaces preserved as the hierarchy indicator** (same as the Excel
   export we worked from). Some rows have an `indent` field directly —
   prefer `indent` if present, fall back to counting leading spaces / 4.

3. The last row in `rows` is the Total row.

4. Strip the company suffix (e.g. `" - JEWIPL"`) using the abbr from the
   Company DocType — look up `frappe.db.get_value("Company",
   filters["company"], "abbr")`.

5. Build the openpyxl Workbook in memory, save to BytesIO, return the
   bytes + filename. Filename pattern:
   `TB_{abbr}_{from_date}_{to_date}.xlsx`.

The visual logic — fills, fonts, borders, outline grouping, formula
strings, the tie-status banner — is otherwise identical to `build_v5.py`.

### 4.6 Reference implementation

The full reference build script from the planning session is appended
verbatim at the bottom of this document under §9. Use it as the source
of truth for visual treatment. Adapt the data-loading section to
operate on `columns` + `rows` instead of reading a source `.xlsx`.

---

## 5. Test plan

### 5.1 Unit tests (must pass before any deployment)

In `formatted_reports/trial_balance/tests/test_builder.py`:

1. **Test parsing**: feed a small synthetic `rows` structure mimicking
   ERPNext's output → verify `is_group` detection, indent levels,
   suffix stripping.
2. **Test number formatting**: zeros become `None`, non-zeros preserve
   value.
3. **Test hierarchy classification**: top-groups vs sub-groups vs
   deeper groups vs leaves are correctly identified for a known
   structure.
4. **Test tie computation**: given total row with Closing Dr=100,
   Closing Cr=100, banner is "tied" (green); with mismatch, banner is
   "out of balance" (red).
5. **Test file-output integrity**: the resulting Workbook has Summary
   and Detail sheets, expected named ranges, no `#REF!` or `#NAME?`
   errors after `scripts/recalc.py`.

Run with: `bench --site erp.jewonline.in run-tests --app dux_voucher --module dux_voucher.formatted_reports.trial_balance.tests.test_builder`

### 5.2 Integration test on dev server

After installation on `erp.jewonline.in`:

1. Open Trial Balance report → confirm "Download Formatted TB" button
   appears in the Export menu group.
2. Set filters: Company = `JEWIPL`, Period = `FY 2026-2027`. Click button.
3. Verify file downloads automatically; opens cleanly in Excel desktop
   (NOT just LibreOffice).
4. Compare visually against `TB_JEWIPL_v5.xlsx` from the planning
   session — Summary sheet's status banner, Closing Position, Period
   Activity match; Detail sheet's hierarchy fills, hairlines, outline
   grouping match. The numbers will differ if the data has changed
   since 28 Apr 2026, that's expected.
5. Repeat with Company = `DD` to confirm it works for entities other
   than JEWIPL (suffix-stripping, missing top groups handled correctly).

### 5.3 Upgrade-safety smoke test

Add `dux_voucher/formatted_reports/trial_balance/tests/test_smoke.py`
that runs after every `bench update`:
- Asserts ERPNext's `execute()` returns columns containing each of the
  seven expected fieldnames.
- Asserts the Client Script with our marker name still exists and is
  enabled.

---

## 6. Phased rollout

### Phase 1 — local + dev server (THIS SESSION)

1. Branch off (`feature/formatted-tb-export`).
2. Scaffold the module structure per §4.1.
3. Implement `builder.py` adapting `build_v5.py` reference.
4. Implement `api.py` with whitelisted method.
5. Implement `client_script.py` with the Custom Script installer.
6. Wire `after_install` and `after_migrate` hooks.
7. Run unit tests locally — STOP for review.
8. Push branch to dux_voucher GitHub.
9. On dev server: pull branch, `bench --site erp.jewonline.in migrate`,
   verify Client Script row created.
10. Run integration test §5.2 — STOP for review with screenshot to user.

### Phase 2 — merge to main

11. Address review feedback.
12. Open PR `feature/formatted-tb-export → main`.
13. After merge, tag `formatted-tb-v1.0.0`.

### Phase 3 — production (deferred, user will trigger)

14. On production server, pull tag, `bench migrate`.
15. Smoke-test with one Company.
16. Announce to RGI users.

---

## 7. Working discipline (from prior project)

- **Prose before code** on any non-trivial component. Sketch the
  approach in a comment block, get user buy-in, then implement.
- **STOP for review at every numbered checkpoint above.** Do not
  silently roll past phase boundaries.
- **Small focused commits** — one per logical step. Don't bundle
  scaffolding + implementation + tests in one commit.
- **Flag architecture drift** before coding around it.
- **Never re-implement accounting logic.** If the data shape from
  `execute()` doesn't match what we need, the right fix is to call
  `execute()` correctly, not to recompute totals ourselves.

---

## 8. Open questions for user

If you hit any of these during implementation, **stop and ask**:

1. Frappe v15 vs v16 — should we target both with a compatibility shim,
   or v16-only? (The dev server is 16.12; production version is unknown
   to me.)
2. Filename convention — `TB_JEWIPL_2026-04-01_2027-03-31.xlsx`
   confirmed, or different?
3. Should the formatted export hide the native "Export" button, or live
   alongside it? (Default: live alongside.)
4. Permissions — who can use the button? Default: same role permissions
   as the standard Trial Balance report (System Manager, Accounts User,
   etc.). Don't add separate role gating unless asked.

---

## 9. Reference implementation — build_v5.py

> The script below was used in the planning session to generate
> `TB_JEWIPL_v5.xlsx` from the raw ERPNext-exported `.xlsx`. The
> visual logic (fills, fonts, borders, outline, banner, tie-check)
> is the source of truth. Adapt the data-loading sections to operate
> on ERPNext's in-memory `columns` + `rows` instead of an Excel file.

```python
# === build_v5.py (planning-session reference) ===
# (see PASTE-BELOW marker — Aditya will paste the full script here
#  when the file lands in the repo, since it's ~370 lines and lives
#  in a separate file in the chat artefacts)
#
# Path in chat: /home/claude/work/build_v5.py
# Source       : produced by Claude in claude.ai planning session,
#                28 Apr 2026
```

The full source has been attached separately as `build_v5_reference.py`
in this commit. Read it end-to-end before starting `builder.py`.
