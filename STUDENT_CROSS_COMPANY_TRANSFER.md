# Cross-Company Student Fee Transfer — Design Study

The real requirement behind "make student entries from one place".

**What the users actually need:** a student pays at one institute, then moves
to another — or the fee is collected at the institute but belongs to the
hostel entity. The credit must move to the other company's books. They asked
for it as *"give students access in JV so we can see the student ledger and
transfer the money from one place to another."*

The app cannot do this today. Not awkwardly — there is no path at all.

Companion to [STUDENT_ENTRY_CONSOLIDATION.md](STUDENT_ENTRY_CONSOLIDATION.md),
which studied the single-company picture. Branch `feature/new-student-module`.

---

## 1. Why it is blocked — five company locks

| Lock | Evidence |
|---|---|
| The master: `company` is reqd, dedup is (name, father, course, company) | [student.py:85-104](dux_voucher/dux_voucher/doctype/student/student.py:85) |
| The account is a per-company convention name | [student_fee.py:29,51](dux_voucher/dux_voucher/api/student_fee.py:29) |
| The balance formula filters on company | [student_fee.py:151-168](dux_voucher/dux_voucher/api/student_fee.py:151) |
| The ledger takes a required company | [reports_api.py:1036](dux_voucher/dux_voucher/api/reports_api.py:1036) |
| Even the picker: `WHERE company=%(co)s` | [reports_api.py:1223](dux_voucher/dux_voucher/api/reports_api.py:1223) |

Underneath all five: **a student is never a GL party.** No JE line anywhere in
the app carries one. That is precisely why "students in JV" has no surface —
in ERPNext, putting a name on a ledger line means making it a Party Type.

The `Student` docstring states the design intent plainly
([student.py:9-14](dux_voucher/dux_voucher/doctype/student/student.py:9)): a student is
at one institution at a time, and the same person at two institutes is **two
unrelated records** — no link, no shared id.

---

## 2. What already exists that helps

**The Inter-Company Transfer module is structurally the right shape.** For a
student fee the required posting is *identical* to a `transfer_type="Payment"`
ICT with the bank leg swapped for the fee liability:

```
Company A:  Dr  Admission/Registration Fee (Provisional) - A
                Cr  Branch & Division (B) - A
Company B:  Dr  Branch & Division (A) - B
                Cr  Admission/Registration Fee (Provisional) - B
```

Reusable as-is:

- `_get_ic_account` — the whole Branch & Division resolution, and the
  direction flip between stages is already correct
  ([:151](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:151) vs
  [:178](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:178))
- `_build_je` — 2-line builder that already stamps `custom_source_voucher`,
  so **two-way cancel comes free**
  ([:205-226](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:205))
- The two-stage confirm handshake and its permission gate
  ([:104-138](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:104),
  [:228-243](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:228))
- Both-sides row scoping, wired at [hooks.py:49-55](dux_voucher/hooks.py:49)

**Only one thing restricts ICT to cash, and it is one line.** The server has
exactly one account-type check in the whole module, on stage 2 only —
[:122-124](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:122).
Stage 1's bank/cash restriction is **client-side only** (picker filters at
`inter_company_transfer.js:88-97`); `_validate_basics` asserts no account type.

**And the ledger renderer is already company-agnostic.**
`_build_student_ledger` takes `company` and uses it in exactly one place —
echoing it to the page header ([reports_api.py:1179](dux_voucher/dux_voucher/api/reports_api.py:1179)).
A cross-company statement needs no renderer change, no print change and no
Excel change: collect entries from both companies and pass a combined label.

---

## 3. Three designs, stress-tested

### Design B — make Student an ERPNext Party Type · **NOT VIABLE**

This is the users' literal ask, and it is the wrong thing to build.

- **Ex-student opening balances are not decomposable into parties, ever.**
  `Ex Student Opening Batch` posts ONE aggregated 2-line JE for the batch
  **net**, not per student
  ([:85-110](dux_voucher/dux_voucher/doctype/ex_student_opening_batch/ex_student_opening_batch.py:85)) —
  and posts nothing at all when the batch is gross-zero. The per-student
  information was never in GL, so no backfill can recover it.
- **The `account_type` flip breaks six posting paths at once**, on a live
  69-company site, with no partial rollout: ERPNext would then *require* a
  party on every line hitting those accounts, and six controllers append
  without one.
- **It does not solve identity — it relocates the problem into immutable GL.**
  Two Student records for one human become two parties.
- **"It naturally spans companies" is false at the query layer.**
  `get_ledger_statement` takes `company` as a required scalar and filters
  `gle.company=%(company)s`. Party-ness changes nothing about that.
- **Its success condition is the raw ERPNext Journal Entry form, handed to
  counter staff** — the exact screen this product exists to hide.

What it gets right, and is worth keeping in mind long-term: putting a party on
the fee accounts *is* the correct accounting shape, and it would shrink the
Trial Balance's permanent "(Unattributed)" row. Not now.

### Design C — an entry mode on PV/RV plus a remarks convention · **NOT VIABLE**

The vehicle cannot make the posting. Every non-party mode on both vouchers
forces a Bank/Cash account and a strictly positive net balanced by that leg.
A book-only two-legged transfer is not expressible. It is also the
unauditable hole documented in the companion study.

### Design A — a "Student Fee Transfer" sibling of ICT · **VIABLE, with caveats**

Recommended. But it is real work, not a clone — see §4.

---

## 4. What makes Design A real work

Four things, and the first is the whole job.

**1. The balance formula must learn about transfers.** This is the core, not
the JE posting. `_student_provisional_balance` defines
`remaining = paid − refunded − income_booked` from receipt/refund **document**
totals ([student_fee.py:138-178](dux_voucher/dux_voucher/api/student_fee.py:138)).
A transfer that only posts JEs leaves it untouched, so:

- **Company A can still refund, and still `book_income`, on money it no longer
  holds.** `book_income` sizes its JE from that same formula.
- **Company B cannot use the money it now holds.** At B the student is a
  different record with no receipts, so `remaining` is 0 while B's GL carries a
  real credit — B can neither refund it nor book it to income.

Fix: add transfers as a fourth leg to the formula (in **both**
implementations — `_student_provisional_balance` and the report's
`_bulk_balances`, which are duplicated logic), or have the transfer write
refund-shaped and receipt-shaped rows. Do not leave two definitions live.

**2. Do not copy ICT's stage-2 account picker.** ICT asks the receiving side
"which of your bank accounts did the cash land in?" because only they know.
For a student fee the destination account is fully deterministic —
`get_admission_fee_account(to_company)`. Stage 2 should ask *"do you accept
this student's credit?"*, not "pick an account".

**3. The mirror JE posts on the ORIGINAL date.** `_build_je` stamps
`je.posting_date = self.transaction_date`
([:209](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:209)).
Journal Entry is under the backdating policy ([hooks.py:36-39](dux_voucher/hooks.py:36)),
so confirming three days later posts a three-day-backdated JE and may be
rejected with an error naming *Journal Entry*. **This bug is live in ICT
today.**

**4. Add an `insert()` override.** `InterCompanyTransfer` has none —
verified, `grep -n "def insert"` returns nothing across all 318 lines — and
`on_cancel` does not null `from_je`/`to_je`. Amending a cancelled transfer
will throw *"Cannot link cancelled document"*. Do not inherit that.

Also note: the permission layer is **not** reusable as-is —
`get_ict_permission_query` hardcodes the table and field names in SQL
([ic_transfer_api.py:123-125](dux_voucher/dux_voucher/api/ic_transfer_api.py:123)).
And `_get_ic_account` needs a Branch & Division leaf per company pair, which
**nothing in the repo creates**.

---

## 5. Independent problems found on the way

**`Student.company` is freely editable.** Plain reqd Link, no `set_only_once`,
no guard, and the master carries no `unique` constraint either
([student.json](dux_voucher/dux_voucher/doctype/student/student.json)). An
operator can move a student with submitted receipts today — silently stranding
the balance in the origin company while every student screen follows the
record. Since there is no other way to "move" a student, **this may already be
happening as a workaround.** `Student` has `track_changes: 1`, so `tabVersion`
will show whether it has.

**The student ledger endpoints have no permission check at all.**
`get_student_ledger` and `search_students` are bare `@frappe.whitelist()` with
no company scoping — `get_permitted_companies` exists at
[reports_api.py:979](dux_voucher/dux_voucher/api/reports_api.py:979) but is called
only from `trial_balance.py`. Any logged-in user can read any student's ledger
in any company. Widening these to span companies makes it worse, so gate them
in the same change.

**`utils.on_journal_entry_submit` imports a function that does not exist.**
`mark_mirror_complete` is not defined in `ic_transfer_api.py` (read in full).
Harmless today because Journal Entry has no `on_submit` hook registered — but
anyone extending ICT who wires that hook gets an ImportError on every submit.
Completion is actually handled inline at
[:134-137](dux_voucher/dux_voucher/doctype/inter_company_transfer/inter_company_transfer.py:134).
Delete the vestigial handler or implement it.

---

## 6. Recommendation

Build **Design A**, in this order:

1. **Guard `Student.company`** against editing once submitted receipts exist,
   and check `tabVersion` for how often it has already happened. Cheap, stops
   silent corruption while the rest is built.
2. **Gate + widen the ledger** — add the missing permission check, then accept
   a company list in `get_student_ledger` and `search_students`. The renderer
   needs no change.
3. **Build Student Fee Transfer** on the ICT pattern, with the four
   corrections in §4.
4. **Ex-students** last — they are out of scope for A and the Student Ledger
   page unifies both kinds, so a transferring ex-student is a visible gap
   until then.

Identity stays the honest limitation in every option: the transfer document
must name `from_student` and `to_student` explicitly, and someone has to
create the destination record. Anything better means a shared person master,
which is its own project.

## 7. To verify on dev before building

1. How many `Student.company` edits already happened (`tabVersion`), and how
   much money is stranded by them.
2. Which company pairs actually need Branch & Division accounts, and whether
   they exist — `_get_ic_account` throws three different ways and nothing
   seeds them.
3. Whether the `Inter-Company Transfer Settings` mapping table is populated at
   all on the live site; with no rows every ICT throws.
