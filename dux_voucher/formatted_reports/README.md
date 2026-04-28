# Formatted Reports

This module produces polished, presentation-ready Excel exports of standard
ERPNext financial reports. The first deliverable is a formatted Trial
Balance; future siblings will cover Balance Sheet, Profit & Loss, and
General Ledger.

The contract is simple and deliberately narrow: the standard ERPNext
report computes the data, and this module re-formats it for human
consumption. **No accounting logic is ever re-implemented here.** If
the numbers are wrong in the standard report, that's where the fix
belongs.

## Layout

```
formatted_reports/
├── PLAN.md                       # Locked v5 design contract — read first.
├── build_v5_reference.py         # Pre-Frappe planning-session reference; do
│                                  not import. Visual logic source-of-truth.
├── trial_balance/
│   ├── api.py                    # @frappe.whitelist() entry point.
│   ├── builder.py                # openpyxl workbook builder.
│   ├── client_script.py          # Idempotent Client Script DocType installer.
│   └── tests/
└── README.md                     # This file.
```

## How it wires up

1. `hooks.py` registers `client_script.ensure_custom_script` as both
   `after_install` and `after_migrate` so the "Download Formatted TB"
   button on the standard Trial Balance report survives upgrades.
2. The button calls `api.export_formatted_tb(filters)` server-side.
3. `api.py` calls `erpnext.accounts.report.trial_balance.trial_balance.execute(filters)`
   to obtain `columns + rows`, then hands them to `builder.build_formatted_tb(...)`.
4. The builder returns `(xlsx_bytes, filename)`, which the API wraps in
   a private `File` doctype and returns the `file_url` to the client.
5. The client opens the file URL — Excel desktop downloads it.

## Adding a new formatted report

Drop a new sibling next to `trial_balance/` (e.g. `balance_sheet/`) with
the same `api.py` + `builder.py` + `client_script.py` shape, register
its installer in `hooks.py`, and follow the v5 design language for
visual consistency.
