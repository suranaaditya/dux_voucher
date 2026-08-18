# Student Accounting Consolidation — Study & Proposal

Study phase for DUX_HANDOFF_2 §5: *"make all student-related accounting
entries from one place."*

Branch: `feature/new-student-module` @ `aafe65f`. No code written yet —
this document is the study and the proposal. Every claim below carries
`file:line` evidence read from source on this tip.

---

## 1. Every path student money takes to the GL

The app **never writes `GL Entry` directly**. Verified:

```
grep -rn "new_doc(['\"]GL Entry['\"]\|make_gl_entries" --include=*.py .
→ no matches
```

Everything goes through a submitted **Journal Entry** or **Payment Entry**,
and ERPNext's own controller produces the GL rows. There are exactly
**14** JE/PE construction sites in the app; nine of them can carry student
money.

### 1a. The sanctioned paths (7)

All post a single 2-line JE. **None of them sets `party_type` / `party`
on any line** — students of either kind are invisible to every GL-party
report.

| # | Screen | Debit | Credit | Also writes | JE link back |
|---|---|---|---|---|---|
| 1 | **Student Fee Receipt** `on_submit` | `received_in_account` | `Admission/Registration Fee (Provisional) - {abbr}` | — | `custom_source_voucher` |
| 2 | **Student Fee Refund** `on_submit` | `Admission/Registration Fee (Provisional)` | `paid_from_account` | — | `custom_source_voucher` |
| 3 | **`book_income()`** (button) | `Admission/Registration Fee (Provisional)` | `Income From Admi Cancellation - {abbr}` *(or Settings override)* | stamps `refund.income_*` | **none — deliberately** |
| 4 | **Ex Student Opening Batch** `on_submit` | net>0 `Ex-Students Receivable`, net<0 `Temporary Opening` | the other one | *N* `Ex Student Ledger Entry` rows | `custom_source_voucher` |
| 5 | **Ex Student Receipt** `on_submit` | `received_in_account` | `Ex-Students Receivable - {abbr}` | 1 ESLE row (credit) | `custom_source_voucher` |
| 6 | **Ex Student Refund** `on_submit` | `Ex-Students Receivable` | `paid_from_account` | 1 ESLE row (debit) | `custom_source_voucher` |
| 7 | **Ex Student Writeoff** `on_submit` | `writeoff_account` (root_type Expense) | `Ex-Students Receivable` | 1 ESLE row (credit) | `custom_source_voucher` |

Evidence:

1. [student_fee_receipt.py:251-265](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py:251);
   account via `get_admission_fee_account` ([student_fee.py:33-60](dux_voucher/dux_voucher/api/student_fee.py:33)),
   `voucher_type` from the **account's** type ([:229-232](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py:229))
2. [student_fee_refund.py:227-241](dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.py:227)
3. [student_fee.py:286-316](dux_voucher/dux_voucher/api/student_fee.py:286);
   income account via [`get_retained_income_account`:188-225](dux_voucher/dux_voucher/api/student_fee.py:188)
4. [ex_student_opening_batch.py:99-110](dux_voucher/dux_voucher/doctype/ex_student_opening_batch/ex_student_opening_batch.py:99),
   ledger rows [:115-127](dux_voucher/dux_voucher/doctype/ex_student_opening_batch/ex_student_opening_batch.py:115)
5. [ex_student_receipt.py:92-104](dux_voucher/dux_voucher/doctype/ex_student_receipt/ex_student_receipt.py:92)
6. [ex_student_refund.py:155-167](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.py:155)
7. [ex_student_writeoff.py:106-118](dux_voucher/dux_voucher/doctype/ex_student_writeoff/ex_student_writeoff.py:106)

**Four control accounts, all resolved by per-company name convention,
none of them auto-created:**

| Account | Resolver |
|---|---|
| `Admission/Registration Fee (Provisional) - {abbr}` | [student_fee.py:29,51](dux_voucher/dux_voucher/api/student_fee.py:29) |
| `Income From Admi Cancellation - {abbr}` | [student_fee.py:134,216](dux_voucher/dux_voucher/api/student_fee.py:134) — Settings override wins |
| `Ex-Students Receivable - {abbr}` | [api/utils.py:123](dux_voucher/dux_voucher/api/utils.py:123) |
| `Temporary Opening - {abbr}` | [api/utils.py:124](dux_voucher/dux_voucher/api/utils.py:124) |

### 1b. The unsanctioned paths (2, plus 2 non-GL)

**8. Receipt Voucher — Head-wise or Party + Head.**
**9. Payment Voucher — Head-wise or Party + Head.**

These reach the *same four control accounts* with no guard whatsoever.
See §2.

**10. A plain ERPNext Journal Entry.** Outside this app entirely; every
Accounts User has it.

**11. Direct edit or delete of an `Ex Student Ledger Entry` row.** Changes
a student's balance with **no GL counterpart at all** — see §5b.

---

## 2. The overlap — yes, and they post differently

> *Can the same collection be booked through both a Receipt Voucher and a
> Student Fee Receipt, and would the two post differently?*

**Yes to both.** This is the single most important finding.

### 2a. Reachability

`RV Account Row.account` and `RV Combined Row.account` are plain
`Link → Account`, `reqd: 1`, with **no** `link_filters`
([rv_account_row.json:18-26](dux_voucher/dux_voucher/doctype/rv_account_row/rv_account_row.json:18),
[rv_combined_row.json:44-52](dux_voucher/dux_voucher/doctype/rv_combined_row/rv_combined_row.json:44)).

The only narrowing anywhere is client-side, and it is exactly two filters:

```js
// receipt_voucher.js:646-662  — identical block at payment_voucher.js:672-688
frm.set_query("account", "account_rows",  () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
frm.set_query("account", "combined_rows", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
```

`Admission/Registration Fee (Provisional) - {abbr}` is by construction a
per-company **non-group leaf**, so it passes both filters and appears in
the picker. The server never re-checks: `_validate_head_wise`
([receipt_voucher.py:107-131](dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.py:107))
and `_validate_combined` ([:280-319](dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.py:280))
check only presence, sign, and not-both-sides. Never `account_type`,
never `is_group`, never `company`.

There is no allow-list, exclusion or warning anywhere:

```
grep -rn 'Admission|ADMISSION_FEE_LEAF|admission' \
  doctype/receipt_voucher/ doctype/payment_voucher/ \
  api/utils.py api/payment_voucher_api.py
→ zero matches
```

And the permissions do not separate the paths: any **Accounts User** who
can raise a Student Fee Receipt can equally raise the RV that bypasses it
(RV grants Accounts User + Accounts Manager,
[receipt_voucher.json:226-257](dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.json:226);
SFR grants those two plus System Manager,
[student_fee_receipt.json:226-272](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.json:226)).

### 2b. The two JEs, leg by leg

| | Student Fee Receipt | Receipt Voucher Head-wise |
|---|---|---|
| Cr | `Admission Fee (Prov)` `total_amount` | `Admission Fee (Prov)` `row.credit` |
| Dr | `received_in_account` `total_amount` | `received_in_account` `net_debit` |
| `voucher_type` | from **account** type ([sfr:229-232](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py:229)) | from **MOP** type ([rv:225-226](dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.py:225)) |
| `user_remark` | auto: `"Admission fee — {name} ({year})"` ([:240-245](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py:240)) | `self.remarks or ""` ([:234](dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.py:234)) |
| line `user_remark` | `"From {name}"` on the Cr leg ([:255-257](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py:255)) | none |
| party fields | none | none |
| student identity | `custom_source_voucher` → SFR → `student` | **none, at any level** |

Same two accounts, same two sides, same amounts. Both output spaces for
`voucher_type` are `{Cash Entry, Bank Entry}` — so with a Bank MOP and a
Bank account **both read `Bank Entry`** and the field does not
discriminate. The *only* reliable discriminator is
`custom_source_voucher_doctype` on the **Journal Entry parent** — which
is not on the GL Entry row.

### 2c. Why it matters — the arithmetic silently breaks

Every student-side balance in the app is computed from **documents, not
GL**:

- `Admission Fee Register` → `FROM \`tabStudent Fee Receipt\` WHERE docstatus=1`
  ([admission_fee_register.py:107-116](dux_voucher/dux_voucher/report/admission_fee_register/admission_fee_register.py:107))
- `_total_paid_by_student` → same table ([student_fee.py:90-99](dux_voucher/dux_voucher/api/student_fee.py:90))
- `_student_provisional_balance` → `remaining = paid − refunded − income_booked`,
  all three from `tabStudent Fee Receipt` / `tabStudent Fee Refund`
  ([student_fee.py:151-178](dux_voucher/dux_voucher/api/student_fee.py:151))
- `get_student_ledger` → unions the same two tables
  ([reports_api.py:1098,1119](dux_voucher/dux_voucher/api/reports_api.py:1098))

So an RV-booked admission fee:

1. **Is invisible** to the Admission Fee Register — count, Total Collected
   and Distinct Students all under-report.
2. **Leaves a real Cr balance** on `Admission Fee (Provisional)` that
   `remaining` reports as **zero**.
3. **Cannot be booked to income.** `book_income` throws *"no remaining
   provisional balance"* at [student_fee.py:276-280](dux_voucher/dux_voucher/api/student_fee.py:276)
   because its arithmetic never saw the RV. The money is stranded in the
   liability permanently.
4. Meanwhile the GL surfaces — Trial Balance, Day Book, Ledger Statement —
   see both bookings **identically**, because both are ordinary submitted
   JEs hitting the same account.

That is the contradiction: **the GL and the student sub-ledger disagree,
and nothing in the app cross-checks them.**

Worth knowing before touching any of it: **"remaining" is implemented
twice.** `_student_provisional_balance` does three single-student SUMs
([student_fee.py:138-178](dux_voucher/dux_voucher/api/student_fee.py:138));
`_bulk_balances` does the same three as one `GROUP BY student` per leg
([student_fee_refund_income.py:137-167](dux_voucher/dux_voucher/report/student_fee_refund_income/student_fee_refund_income.py:137)).
Same filters, same subtraction, two places to keep in step. A third sum,
`_total_paid_by_student` ([student_fee.py:69-99](dux_voucher/dux_voucher/api/student_fee.py:69)),
backs the refund form's headline and **has no `company` filter** where the
other two do — harmless today only because a `STU-####` id belongs to
exactly one company, but a latent inconsistency if that ever changes.

The mirror leak is open on the payment side — a Payment Voucher Head-wise
row `Dr Admission/Registration Fee (Provisional)` produces the same JE a
Student Fee Refund posts ([payment_voucher.py:276-295](dux_voucher/dux_voucher/doctype/payment_voucher/payment_voucher.py:276)),
with no student, no heads, and no `income_*` tracking. The same applies to
`Ex-Students Receivable` in both directions, where the damage is worse
because that account's per-student split exists **only** in a
denormalised table (§3a).

### 2d. A second, already-live divergence

Independent of the RV leak: **the Student Ledger page is blind to the
income booking.**

`book_income` debits `Admission Fee (Provisional)`
([student_fee.py:296-302](dux_voucher/dux_voucher/api/student_fee.py:296)), but
`get_student_ledger` reads only Student Fee Receipt and Student Fee Refund
— confirmed, `grep -n "income_je\|income_booked" api/reports_api.py`
returns nothing.

So once retained fee is booked to income, the Student Ledger keeps showing
a Cr balance of `paid − refunded` that **no longer exists in GL**. It
overstates the liability by exactly `income_amount`. This is live today,
with no RV involved. Not previously recorded.

---

## 3. What a unified screen must cover — and what it cannot absorb

### 3a. Cannot be absorbed without losing something

**1. The ex-student ledger is not GL-derived, and cannot become so
cheaply.** `Ex-Students Receivable - {abbr}` is **one account shared by
every ex-student in the company** ([api/utils.py:123](dux_voucher/dux_voucher/api/utils.py:123)),
and the JE lines carry no party. The per-student split exists **only** in
`Ex Student Ledger Entry`, read by
`_current_outstanding` = `SUM(debit) − SUM(credit) WHERE is_cancelled = 0`
([ex_student_api.py:140-150](dux_voucher/dux_voucher/api/ex_student_api.py:140))
and by `recompute_opening_balance` ([ex_student.py:31-55](dux_voucher/dux_voucher/doctype/ex_student/ex_student.py:31)).
A "just post to GL and read it back" unification **deletes per-student
balances**. Fixing it properly means making students GL parties — a
separate, larger project (§4d).

Three things make that table more fragile than it looks:

- **The ledger row does not store the JE name.** `_insert_ledger_entry`
  takes `je_name` and never uses it
  ([ex_student_receipt.py:109-120](dux_voucher/dux_voucher/doctype/ex_student_receipt/ex_student_receipt.py:109),
  [ex_student_refund.py:172-192](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.py:172));
  the writeoff's does not even take it
  ([:123](dux_voucher/dux_voucher/doctype/ex_student_writeoff/ex_student_writeoff.py:123)).
  The only bridge is `voucher_no` → parent doc → `parent.backend_je`.
- **Rows are cancelled by raw SQL** keyed on `(voucher_type, voucher_no)`,
  bypassing the document layer entirely — no hook, no Version row
  ([ex_student_receipt.py:129-137](dux_voucher/dux_voucher/doctype/ex_student_receipt/ex_student_receipt.py:129) and the three siblings).
- **Nothing reconciles the table against GL.** Eight files read
  `tabEx Student Ledger Entry`; not one of them also queries `tabGL Entry`,
  and `scheduler_events` runs only `tb_aggregate.rebuild_nightly`
  ([hooks.py:61-65](dux_voucher/hooks.py:61)). The two ledgers can only
  drift, and nothing would detect it.

Related reporting bug found on the way: `Ex Student Outstanding` builds its
*Received* and *Written Off* columns as `voucher_type`-filtered sums of
`le.credit` ([ex_student_outstanding.py:60-65](dux_voucher/dux_voucher/report/ex_student_outstanding/ex_student_outstanding.py:60)),
so **Ex Student Refund rows land in neither column** — they are visible only
inside the signed total.

**2. The opening batch deliberately posts NET, and sometimes nothing at
all.** [ex_student_opening_batch.py:85-88](dux_voucher/dux_voucher/doctype/ex_student_opening_batch/ex_student_opening_batch.py:85):

```python
net = flt(self.net_amount)
if abs(net) < 0.005:
    # Gross-zero batch (total_debit == total_credit). Skip JE; ledger rows still recorded.
    return None
```

A batch of Dr 100,000 (student A) + Cr 100,000 (student B) writes **two
ledger rows and zero GL**. This is intentional and it aggregates
correctly, but it means the batch is *structurally* a bulk sub-ledger
loader, not a voucher. A one-student-at-a-time screen cannot express it.

**3. The CSV path auto-creates masters.** `import_from_csv`
([ex_student_api.py:10-96](dux_voucher/dux_voucher/api/ex_student_api.py:10))
sniffs the delimiter, tolerates a legacy `amount` column, and calls
`_get_or_create_ex_student` ([:121-137](dux_voucher/dux_voucher/api/ex_student_api.py:121))
to mint Ex Student records on the fly. It also `frappe.db.commit()`s
mid-request ([:90](dux_voucher/dux_voucher/api/ex_student_api.py:90)).
Bulk import is a different interaction from a counter voucher and should
stay its own screen.

**4. The three soft-warn dialogs are the reason two of these doctypes
exist.** The refund docstrings say so explicitly
([student_fee_refund.py:12-18](dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.py:12),
[ex_student_refund.py:7-11](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.py:7)).
They are also **all three broken the same way** — §5c.

**5. Per-doctype print formats and naming series.** `SFR-.YYYY.-`,
`SRF-.YYYY.-`, and seven distinct print formats keyed on doctype. A single
doctype collapses the naming series and forces conditional print
templates.

**6. Backdating rules are keyed on `target_doctype`.** Collapsing screens
into one doctype collapses ten rules into fewer, losing the ability to
allow backdated receipts but not backdated refunds.

### 3b. Must cover

- Both student kinds (Ex + New), company-scoped, from one picker — the
  Student Ledger page already proves this shape works
  ([reports_api.py:1056-1134](dux_voucher/dux_voucher/api/reports_api.py:1056))
- All six directions: new receipt, new refund, ex receipt, ex refund,
  ex writeoff, retained-fee income booking
- The course-scoped fee-head child table (new-student only)
- Live balance headline before posting — `get_student_remaining` for new,
  `get_outstanding` for ex
- The soft-warns, **server-side this time**
- The `insert()` amend scrub, on every submittable it routes to
- Cancel cascade in both directions, unchanged

---

## 4. Recommendation

### 4a. Not a new doctype

A new submittable "Student Voucher" means a third writer to the same four
control accounts. The existing seven do not go away — they hold live
submitted documents that reports read by table name. You would have to
either migrate that data (risky, and `Ex Student Ledger Entry.voucher_no`
is a Dynamic Link into those doctypes) or keep both, which makes the
overlap problem **worse**, not better. It also collapses the naming
series, the print formats and the per-doctype backdating rules (§3a.5-6).

### 4b. Not an entry mode on PV/RV

`entry_mode` is a `Select` whose string is dispatched on in both
controllers ([receipt_voucher.py:43-48](dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.py:43),
[payment_voucher.py:49-56](dux_voucher/dux_voucher/doctype/payment_voucher/payment_voucher.py:49)).
Receipt Voucher is already 28 fields with 5 mode-gated sections; Payment
Voucher is 32 with 6. Adding a student mode means new child tables, a
`student`/`admission_year`/`course` block, edits to two controllers and to
two ~1,100-line JS files — and the modes are already asymmetric (PV has
Contra, RV does not). It would also put student entry **inside the very
screens whose account picker is the leak**, which invites exactly the
confusion we are trying to remove.

### 4c. Recommended — a Page that routes to the existing controllers

Build **`/app/dux-student-entry`**, a Frappe **Page** (not a doctype) that
is a router: pick company → pick student kind + student → pick action →
one form → it constructs and submits the *existing* doctype server-side
via a thin whitelisted API, and shows the resulting document.

Why this one:

- **Zero new GL paths.** Every posting still goes through the controller
  that owns it, so `custom_source_voucher`, the cancel cascade, the
  `insert()` amend scrub and the backdating hook all keep working
  untouched.
- **Pages need no migrate and no build** — they load from disk per request
  (CLAUDE.md Deployment). Iteration is a hard refresh. The five existing
  report Pages prove the pattern in this codebase.
- **Reversible.** If it is wrong, delete the Page. Nothing else moved.
- **It does not pretend to fix the sub-ledger.** The ex-student table and
  the opening batch stay as they are, honestly, behind their own entries.

Trade-offs, stated plainly:

- A Page duplicates form logic that a doctype would get free — pickers,
  validation feedback, the fee-head grid. Roughly the effort of
  `dux_student_ledger.js`, and it must not drift from the controllers.
- No native list view, no built-in print button, no Frappe form
  permissions — the whitelisted endpoints must call `check_permission`
  themselves. (Note `payment_voucher_api.py` has **no permission check on
  any of its seven endpoints** — do not copy that.)
- It is a convenience layer. It **does not by itself close the RV/PV
  leak.**

### 4d. Closing the leak is a separate, smaller change — and it comes first

Consolidation is a UX fix. The leak is a correctness fix, and it is much
cheaper. Two options, not mutually exclusive:

1. **Server-side guard (minimal).** In `_validate_head_wise` and
   `_validate_combined` on both vouchers, reject rows whose account is one
   of the four student control accounts, pointing the user at the right
   screen. ~20 lines, plus tests. Catches API and import paths too, which
   the client `set_query` never did.
2. **Make students GL parties (structural).** Register `Student` and
   `Ex Student` as ERPNext `Party Type`s and set `party_type`/`party` on
   the JE lines. This would make the sub-ledger derivable from GL and kill
   the whole class of drift — but it changes the account type semantics of
   the two control accounts and needs the existing rows backfilled.
   **Not verified against the live site** — flagged as design, not fact.

**Suggested order:** guard (4d.1) → verify against real data whether the
leak has already happened → the Page (4c) → revisit 4d.2 separately.

Before building anything: a query against dev to count JEs hitting the
four control accounts whose `custom_source_voucher_doctype` is **not** the
owning doctype. That measures whether this is a theoretical hole or a live
reconciliation problem, and it changes the priority.

---

## 5. Landmines — verified, with three corrections

All four from DUX_HANDOFF_2 §5 were checked against source rather than
rediscovered.

### 5a. `_cancel_parent_voucher` swallows every exception — **CONFIRMED, exactly as stated**

[utils.py:66-70](dux_voucher/dux_voucher/utils.py:66), line numbers exact:

```python
    except Exception as e:
        frappe.log_error(
            title=_("Error cancelling {0} {1}").format(doctype, name),
            message=str(e)
        )
```

Note the asymmetry that makes it dangerous: the *other* direction hard-throws
— `_safe_cancel` raises `frappe.throw` on any cancel failure
([api/utils.py:99-102](dux_voucher/dux_voucher/api/utils.py:99)). So a failed
backend cancel **blocks** the parent cancel, but a failed parent cancel is
**silent**. Cancel the backend JE, have the parent fail, and the parent sits
at `docstatus=1` with its backend cancelled and nothing shown to the user.

Concrete worst case on the ex-student side: the GL is reversed while the
`Ex Student Ledger Entry` rows stay `is_cancelled = 0` — because those rows
are only flagged from the parent's `on_cancel`
([ex_student_receipt.py:129-137](dux_voucher/dux_voucher/doctype/ex_student_receipt/ex_student_receipt.py:129)),
which never ran. The student keeps a balance the books no longer carry, and
the only record is an Error Log row.

### 5b. `Ex Student Ledger Entry` is unguarded — **CONFIRMED, with one mitigation the handoff missed**

[ex_student_ledger_entry.json](dux_voucher/dux_voucher/doctype/ex_student_ledger_entry/ex_student_ledger_entry.json):
no `is_submittable`, no `track_changes` key at all (so it defaults off), and
all three roles including **Accounts User** get `write: 1`, `delete: 1`,
`create: 1`. Controller is `class ExStudentLedgerEntry(Document): pass`
([.py:8-9](dux_voucher/dux_voucher/doctype/ex_student_ledger_entry/ex_student_ledger_entry.py:8)).

**Correction:** `"in_create": 1` **is** set. That hides the "New" button in
the list view — so casual creation is blocked. It does **not** block editing
or deleting an existing row, nor creation via API. The core risk stands: a
student's balance can be changed with no GL counterpart and no audit trail.

### 5c. Soft-warn confirms — **CONFIRMED, and it is three surfaces, not two**

The handoff says "both refunds". It is **three**, with the identical
copy-pasted bug:

- `student_fee_refund.js` — flag at [:120](dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.js:120), set at [:162](dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.js:162), save at [:163](dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.js:163)
- `ex_student_refund.js` — [:98](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.js:98), [:135](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.js:135), [:136](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.js:136)
- `ex_student_receipt.js` (**overpayment warning — not in the handoff**) — [:89](dux_voucher/dux_voucher/doctype/ex_student_receipt/ex_student_receipt.js:89), [:99](dux_voucher/dux_voucher/doctype/ex_student_receipt/ex_student_receipt.js:99), [:100](dux_voucher/dux_voucher/doctype/ex_student_receipt/ex_student_receipt.js:100)

All three end with the same line:

```js
frm.save(frm.doc.docstatus === 0 ? undefined : 'Submit');
```

**Client-side only** — confirmed, no server-side equivalent in any of the
three controllers.

**Sticky** — confirmed, and worse than the handoff says.
`grep -n "_refund_warning_confirmed"` on `student_fee_refund.js` returns
exactly two lines, 120 and 162: set once, never reset. After the first
confirm the operator can change the amount to anything and `validate`
returns at line 120 with no warning. And because the flag lives on `frm` —
and Frappe reuses **one Form instance per DocType across documents** — the
stickiness survives navigating to a *different* refund. Confirm once on one
student's over-refund and every subsequent refund, for every student, is
unwarned for the rest of the browser session.

**Submit → Save downgrade** — confirmed, and the ternary is simply
inverted. `frappe.validated = false` aborts the submit, so when the callback
runs the doc is **still** `docstatus === 0` — the ternary therefore picks
`undefined` and performs a plain Save. The `'Submit'` branch is unreachable
in the case that matters.

### 5d. `no_copy` on amend — **PARTIALLY CORRECT; the stated reason is not the real one**

The overrides exist as described — five of them, all clearing amend-inherited
backend links:

| Doctype | Line | Clears |
|---|---|---|
| Payment Voucher | [:22-42](dux_voucher/dux_voucher/doctype/payment_voucher/payment_voucher.py:22) | `backend_references` |
| Receipt Voucher | [:19-39](dux_voucher/dux_voucher/doctype/receipt_voucher/receipt_voucher.py:19) | `backend_references` |
| Student Fee Receipt | [:62-82](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py:62) | `backend_je`, `is_posted` |
| Student Fee Refund | [:47-64](dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.py:47) | those two **plus all four `income_*`** |
| Ex Student Refund | [:40-51](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.py:40) | `backend_je`, `is_posted` |

Two corrections:

**The fields already carry `no_copy: 1`** — `is_posted` and `backend_je` at
`student_fee_receipt.json:196,203`; `is_posted` and `backend_references` at
`payment_voucher.json:207,219`. So `no_copy` is not being relied on as
absent. Note also that **Payment Voucher and Receipt Voucher have no
`backend_je` field at all** (`grep -c backend_je` on both `.py` and `.json`
→ 0) and their overrides deliberately leave `is_posted` alone, trusting
`no_copy` for it while scrubbing the child table by hand.

**The docstrings give a different, more specific cause, and it is an
*ordering* problem** — [student_fee_receipt.py:63-78](dux_voucher/dux_voucher/doctype/student_fee_receipt/student_fee_receipt.py:63):
`Document.insert` runs `_validate_links()` **before** `before_insert`, so a
`before_insert` cleanup has already thrown *"Cannot link cancelled
document."* Overriding `insert()` is the only hook early enough. That is the
reason to preserve, and it is orthogonal to whether `no_copy` fires on
amend — which cannot be settled from this checkout, since Frappe's source
is not on disk here. Worth restating precisely, because "no_copy doesn't
work on amend" would send someone to fix the wrong thing.

**Ex Student Receipt, Writeoff and Opening Batch have no `insert()`
override** — confirmed, `grep -n 'def insert' doctype/ex_student*/*.py`
matches only `ex_student_refund.py:40`. All three are submittable, carry
`backend_je`, and are therefore amendable. Whether amend actually throws on
them is untested — the whole ex-student module has **zero test coverage**
(all six `test_*.py` files are untouched Frappe scaffolding stubs).

### 5e. Backdating gap (handoff §4.1) — **CONFIRMED, but narrower than stated**

The wiring gap is real. `SUPPORTED_DOCTYPES` lists ten
([dux_backdating_settings.py:22-33](dux_voucher/dux_voucher/doctype/dux_backdating_settings/dux_backdating_settings.py:22));
`doc_events` wires eight ([hooks.py:32-47](dux_voucher/hooks.py:32)).
`grep -n 'Refund' hooks.py` → no matches. **Ex Student Refund** and
**Student Fee Refund** have seeded rules and a configurable UI row, and no
hook of their own. Fix is two lines.

**Correction — they are not actually unenforced.** Both refunds copy their
own posting date onto the backend JE
([student_fee_refund.py:213](dux_voucher/dux_voucher/doctype/student_fee_refund/student_fee_refund.py:213),
[ex_student_refund.py:144](dux_voucher/dux_voucher/doctype/ex_student_refund/ex_student_refund.py:144)),
and `Journal Entry` **is** hooked ([hooks.py:36-39](dux_voucher/hooks.py:36)).
So a backdated refund is still blocked — just:

- under the **Journal Entry** rule's limits, not its own, so its own rule
  row is decorative and a laxer JE rule silently overrides a stricter
  refund rule;
- only at **submit**, not at save, so a backdated draft saves happily;
- with an error message naming *Journal Entry*, which will send the
  operator looking in the wrong place.

Worth restating in the fix commit, because "the rule is never enforced"
predicts a symptom nobody will actually see.

**Additional, not in the handoff:** `Ex Student Writeoff` and
`Ex Student Opening Batch` are in **neither** `SUPPORTED_DOCTYPES` nor
`doc_events`. Both post to GL. The writeoff is caught by the same indirect
JE path; the opening batch is too, *except* in the gross-zero case where no
JE is posted at all (§3a.2) — that one is genuinely uncontrolled.

`DuxBackdatingRule.validate` **is** dead code — the doctype is `istable: 1`
([.json:71](dux_voucher/dux_voucher/doctype/dux_backdating_rule/dux_backdating_rule.json:71))
and Frappe does not run child-table controller `validate()` on a parent
save; the parent's own `validate` calls only `_ensure_default_rules` and
`_reject_duplicate_rules`
([dux_backdating_settings.py:65-66](dux_voucher/dux_voucher/doctype/dux_backdating_settings/dux_backdating_settings.py:65)).
Neither `max_days_*` field carries `non_negative`. The consequence is exact:
with `max_days_back = -5`, `limit_back` is truthy and `days_back > -5` is
true for **every** past date
([backdating.py:82-93](dux_voucher/dux_voucher/api/backdating.py:82)) — the
policy inverts into a total block on backdating (same-day and forward-dated
saves still pass, since the throw sits inside the `posting < today` branch)
while the UI still shows backdating allowed. **The same inversion exists on
the forward side and is not mentioned anywhere:** a negative
`max_days_forward` makes `limit_forward` truthy at
[:103](dux_voucher/dux_voucher/api/backdating.py:103) and
`days_forward > limit_forward` always true at
[:105](dux_voucher/dux_voucher/api/backdating.py:105).

Strictly, `DuxBackdatingRule.validate` is dead *in practice* rather than
unreachable — it would run on a direct `frappe.get_doc("Dux Backdating
Rule", …).save()`, but no such call exists in the app, the doctype is
`istable: 1` with an empty permissions block, and the parent never invokes
it.

---

## 6. Open questions for the next step

1. **Has the leak already fired?** Count JEs on the four control accounts
   whose `custom_source_voucher_doctype` is not the owning doctype. Needs a
   dev-site query.
2. **Can `Student` / `Ex Student` be ERPNext `Party Type`s here?** Design
   assumption in §4d.2 — unverified.
3. Are Ex Student Receipt / Writeoff / Opening Batch reachable via amend
   (§5d)?
