"""Students as GL parties — the per-student ledger.

Until this module a student was never a party on a ledger line: every
admission-fee receipt, refund and income booking credited or debited the
company-wide ``Admission/Registration Fee (Provisional) - {abbr}`` account
with no name on the row, and "how much do we hold for this student" was
re-derived from the receipt and refund *documents*. That made every new
kind of student entry (a transfer to the institute, a hostel fee raised, a
fine, a concession) impossible to express without teaching that document
formula about it.

Now ``Student`` is an ERPNext Party Type and the provisional account is the
student's ledger:

* every line on that account carries ``party_type='Student'`` and the
  student — receipts, refunds, income bookings and Student Journal
  Vouchers all post that way;
* a student's balance is a plain GL sum by party (Cr = we hold money for
  the student, Dr = the student owes us), so anything that moves it is
  seen by everything that reads it;
* the account keeps its blank ``account_type``. ERPNext only *requires* a
  party on Receivable/Payable accounts and only *forbids* one on accounts
  typed Bank/Cash/Income/… (``party.validate_account_party_type``), so a
  blank-typed liability takes a party without turning it mandatory — the
  existing account, its history and every other posting path keep working.

History posted before this existed carries no party. ``migrate`` attaches
the student to those lines (each one belongs to exactly one receipt,
refund or income booking) and then flips ``Student Fee Settings.
student_ledger_migrated``. Until that flag is set, balances keep coming
from the documents, and the Student Journal Voucher refuses to post —
a half-migrated ledger would give wrong balances.
"""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

from dux_voucher.dux_voucher.api.student_fee import (
    ADMISSION_FEE_LEAF,
    get_admission_fee_account,
)


PARTY_TYPE = "Student"
SETTINGS = "Student Fee Settings"


# =====================================================================
# Migration flag
# =====================================================================

def is_migrated():
    """True once the history backfill has run on this site."""
    return bool(cint(frappe.db.get_single_value(SETTINGS, "student_ledger_migrated")))


def require_migrated():
    if not is_migrated():
        frappe.throw(_(
            "The student ledger has not been set up on this site yet. A "
            "System Manager must run the Student Ledger migration (see "
            "<strong>Student Fee Settings</strong>) before student journal "
            "entries can be posted."))


# =====================================================================
# Balances
# =====================================================================

def get_student_balance(student, company):
    """Signed balance of one student in one company, from the GL.

    Positive = credit (money held for the student), negative = debit (the
    student owes). Rows of cancelled vouchers are excluded by
    ``is_cancelled``; vouchers cancelled while ERPNext's immutable ledger
    was on keep both the original and the reversal live, and those two
    net to zero for the student, so the sum stays right either way.
    """
    if not student or not company:
        return 0.0
    row = frappe.db.sql(
        """SELECT COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0)
           FROM `tabGL Entry`
           WHERE company=%(c)s AND party_type=%(pt)s AND party=%(s)s
             AND is_cancelled=0""",
        {"c": company, "pt": PARTY_TYPE, "s": student})
    return flt(row[0][0]) if row else 0.0


def get_student_balances(students, company):
    """``{student: signed balance}`` for many students — one grouped query."""
    students = [s for s in (students or []) if s]
    if not students or not company:
        return {}
    rows = frappe.db.sql(
        """SELECT party, COALESCE(SUM(credit), 0) - COALESCE(SUM(debit), 0)
           FROM `tabGL Entry`
           WHERE company=%(c)s AND party_type=%(pt)s AND party IN %(s)s
             AND is_cancelled=0
           GROUP BY party""",
        {"c": company, "pt": PARTY_TYPE, "s": tuple(students)})
    out = {s: 0.0 for s in students}
    out.update({p: flt(v) for p, v in rows})
    return out


def student_account(company):
    """The company's student ledger account, or None if it has none. Never
    throws — it is consulted on every Journal Entry and Payment Entry."""
    abbr = frappe.get_cached_value("Company", company, "abbr") if company else None
    if not abbr:
        return None
    name = f"{ADMISSION_FEE_LEAF} - {abbr}"
    return name if frappe.db.exists("Account", name) else None


def require_company_access(company):
    """Student balances are per-company money: the caller must be allowed
    the company (same User Permission scoping the report pages use)."""
    from dux_voucher.dux_voucher.api.reports_api import get_permitted_companies
    if company and company not in (get_permitted_companies() or []):
        frappe.throw(_("You do not have access to {0}.").format(company),
                     frappe.PermissionError)


@frappe.whitelist()
def get_balance(student, company):
    """Form helper — the student's balance plus the account it lives on."""
    frappe.has_permission("Student", "read", throw=True)
    require_company_access(company)
    return {
        "balance": get_student_balance(student, company) if is_migrated() else None,
        "account": get_admission_fee_account(company) if company else None,
        "migrated": is_migrated(),
    }


# =====================================================================
# Guards on ERPNext's own vouchers
# =====================================================================

def validate_journal_entry(doc, method=None):
    """A Student on a Journal Entry line must belong to the JE's company and
    sit on that company's student account.

    ERPNext checks neither: the party is a Dynamic Link with no company
    awareness, and a blank-typed account accepts any party. Without this a
    student from one institute could be posted in another's books, or onto
    an unrelated ledger where no student balance would ever see it.
    """
    lines = doc.get("accounts") or []
    rows = [d for d in lines if d.party_type == PARTY_TYPE]
    on_ledger = [d for d in lines
                 if (d.account or "").startswith(ADMISSION_FEE_LEAF + " - ")]
    if not rows and not on_ledger:
        return  # the common case: no student anywhere near this JE

    # Once the ledger is migrated every line on the student account must
    # name its student — a nameless line (a head-wise PV/RV, a manual JV)
    # would move the account without moving any student, and the same money
    # could then be refunded once and transferred again.
    if on_ledger and is_migrated():
        control = student_account(doc.company)
        for d in on_ledger:
            if d.account == control and d.party_type != PARTY_TYPE:
                frappe.throw(_(
                    "Row {0}: {1} is the student ledger — every entry on it must "
                    "name the student. Post student money through Student Fee "
                    "Receipt / Refund or a Student Journal Voucher, or set Party "
                    "Type = Student and the student on this row.")
                    .format(d.idx, control))
    if not rows:
        return
    control = get_admission_fee_account(doc.company)
    for d in rows:
        if not d.party:
            frappe.throw(_("Row {0}: select the Student.").format(d.idx))
        st_company = frappe.db.get_value("Student", d.party, "company")
        if not st_company:
            frappe.throw(_("Row {0}: Student {1} does not exist.").format(d.idx, d.party))
        if st_company != doc.company:
            frappe.throw(_(
                "Row {0}: Student {1} belongs to {2}, not {3}. A student can only "
                "be posted in their own company's books — to move a student's "
                "money to another institute use a Student Journal Voucher "
                "(Transfer to Institute).").format(d.idx, d.party, st_company, doc.company))
        if d.account != control:
            frappe.throw(_(
                "Row {0}: student entries must be posted to <strong>{1}</strong>, "
                "the student ledger account of {2} — not {3}.")
                .format(d.idx, control, doc.company, d.account))


def validate_payment_entry(doc, method=None):
    """Student money moves through Student Fee Receipt / Refund (which post
    the right account with the student on it), never a Payment Entry —
    ERPNext's Payment Entry would resolve the party account on its own and
    skip the student ledger."""
    if doc.get("party_type") == PARTY_TYPE:
        frappe.throw(_(
            "Students cannot be paid or received through a Payment Entry. Use "
            "<strong>Student Fee Receipt</strong> to collect and "
            "<strong>Student Fee Refund</strong> to pay back."))
    if is_migrated():
        control = student_account(doc.get("company"))
        if control and control in (doc.get("paid_from"), doc.get("paid_to")):
            frappe.throw(_(
                "{0} is the student ledger; a Payment Entry cannot name a student "
                "on it. Use Student Fee Receipt / Refund.").format(control))


def student_has_postings(student):
    """True if any live ledger line or submitted student document names the
    student — after which the student's company can no longer change."""
    if frappe.db.sql(
            """SELECT 1 FROM `tabGL Entry`
               WHERE party_type=%s AND party=%s AND is_cancelled=0 LIMIT 1""",
            (PARTY_TYPE, student)):
        return True
    for dt in ("Student Fee Receipt", "Student Fee Refund", "Student Journal Voucher"):
        if frappe.db.exists(dt, {"student": student, "docstatus": 1}):
            return True
    return bool(frappe.db.exists(
        "Student Journal Voucher", {"to_student": student, "docstatus": 1}))


# =====================================================================
# One-time history backfill
# =====================================================================

def _source_lines():
    """Every ledger line that should carry a student but may not yet.

    Yields dicts ``{company, student, je, kind, doc}`` — one per submitted
    receipt, refund and income booking. Each of those JEs was posted by the
    app for exactly one student, so the attribution is exact.
    """
    out = []
    for r in frappe.db.sql(
            """SELECT company, student, backend_je AS je, name
               FROM `tabStudent Fee Receipt`
               WHERE docstatus=1 AND IFNULL(backend_je, '')!=''""", as_dict=True):
        out.append(dict(company=r.company, student=r.student, je=r.je,
                        kind="Receipt", doc=r.name))
    for r in frappe.db.sql(
            """SELECT company, student, backend_je AS je, name
               FROM `tabStudent Fee Refund`
               WHERE docstatus=1 AND IFNULL(backend_je, '')!=''""", as_dict=True):
        out.append(dict(company=r.company, student=r.student, je=r.je,
                        kind="Refund", doc=r.name))
    for r in frappe.db.sql(
            """SELECT company, student, income_je AS je, name
               FROM `tabStudent Fee Refund`
               WHERE docstatus=1 AND income_booked=1 AND IFNULL(income_je, '')!=''""",
            as_dict=True):
        out.append(dict(company=r.company, student=r.student, je=r.je,
                        kind="Income", doc=r.name))
    return out


def _document_balances(company):
    """The pre-migration definition of "remaining", per student:
    receipts − refunds − income booked. Used to prove the backfill."""
    def grouped(sql):
        return {s: flt(v) for s, v in frappe.db.sql(sql, {"c": company})}
    paid = grouped("""SELECT student, SUM(total_amount) FROM `tabStudent Fee Receipt`
                      WHERE docstatus=1 AND company=%(c)s GROUP BY student""")
    refunded = grouped("""SELECT student, SUM(total_amount) FROM `tabStudent Fee Refund`
                          WHERE docstatus=1 AND company=%(c)s GROUP BY student""")
    income = grouped("""SELECT student, SUM(income_amount) FROM `tabStudent Fee Refund`
                        WHERE docstatus=1 AND income_booked=1 AND company=%(c)s
                        GROUP BY student""")
    students = set(paid) | set(refunded) | set(income)
    return {s: flt(paid.get(s)) - flt(refunded.get(s)) - flt(income.get(s))
            for s in students}


@frappe.whitelist(methods=["POST"])
def migrate(dry_run=1, accept_off_account=0):
    """Attach the student to every historic line on the student account.

    ``dry_run=1`` (the default) changes nothing and returns the report; run
    it first, read it, then run with ``dry_run=0``. Only the party columns
    of existing lines are written — no amount, account, date or voucher
    changes — on both ``GL Entry`` and the JE's own ``Journal Entry
    Account`` rows so the voucher and the ledger agree.

    The report proves the result: for every student, the ledger balance
    after the backfill must equal the old document formula. Students where
    it does not are listed (typically a receipt from before the account
    naming was fixed that credited a different ledger) and are NOT a
    reason the run stops — they are what someone has to look at.

    The real run refuses while any such off-account receipt exists unless
    ``accept_off_account=1``: once the flag is on, those students' balances
    come from the ledger and would read short (or in debit, if a refund did
    hit the student account) until each receipt is moved onto the student
    with an *Other Credit to Student* voucher. Accepting means "I will post
    those vouchers straight after".
    """
    frappe.only_for("System Manager")
    dry_run = cint(dry_run)

    if not dry_run and not cint(accept_off_account):
        # Decide before writing anything.
        off = [o for c in migrate(dry_run=1)["companies"] for o in c.get("off_account", [])]
        if off:
            frappe.throw(_(
                "{0} receipt(s) credited a ledger other than the student account "
                "(see the dry-run report, 'off_account'). Re-run with "
                "accept_off_account=1 and then move each onto its student with an "
                "Other Credit to Student voucher — until then those students' "
                "balances read short.").format(len(off)))

    # A line can only be attributed to a student who still belongs to the
    # company it was posted in — otherwise the student's party would sit in
    # another company's books, which every guard here forbids.
    st_company = dict(frappe.db.sql("SELECT name, company FROM `tabStudent`"))
    lines, moved = [], []
    for ln in _source_lines():
        if st_company.get(ln["student"]) != ln["company"]:
            moved.append(dict(kind=ln["kind"], doc=ln["doc"], student=ln["student"],
                              posted_in=ln["company"],
                              student_now_in=st_company.get(ln["student"])))
            continue
        lines.append(ln)
    by_company = {}
    for ln in lines:
        by_company.setdefault(ln["company"], []).append(ln)

    report = {"dry_run": bool(dry_run), "companies": [], "totals": {},
              "student_moved_company": moved}
    tot_gl = tot_jea = 0

    for company in sorted(by_company):
        try:
            control = get_admission_fee_account(company)
        except frappe.ValidationError:
            report["companies"].append({"company": company,
                                        "error": "student account missing"})
            continue

        comp = {"company": company, "account": control, "gl_rows": 0,
                "je_rows": 0, "by_kind": {}, "off_account": [],
                "mismatches": [], "unattributed": {}}

        # The lines each source JE has on the student account, still unnamed.
        jes = {ln["je"] for ln in by_company[company]}
        gl = frappe.db.sql(
            """SELECT name, voucher_no, debit, credit, IFNULL(party, '') AS party
               FROM `tabGL Entry`
               WHERE company=%(c)s AND account=%(a)s AND voucher_type='Journal Entry'
                 AND voucher_no IN %(j)s""",
            {"c": company, "a": control, "j": tuple(jes)}, as_dict=True) if jes else []
        gl_by_je = {}
        for g in gl:
            gl_by_je.setdefault(g.voucher_no, []).append(g)

        for ln in by_company[company]:
            rows = gl_by_je.get(ln["je"], [])
            if not rows:
                # The voucher never touched the student account — note it
                # with the ledger it did hit, so someone can move it.
                hit = frappe.db.sql(
                    """SELECT account, SUM(credit) - SUM(debit)
                       FROM `tabGL Entry` WHERE voucher_no=%s AND is_cancelled=0
                         AND account NOT IN (SELECT name FROM `tabAccount`
                                             WHERE account_type IN ('Bank','Cash')
                                               AND root_type='Asset')
                       GROUP BY account""", ln["je"])
                comp["off_account"].append(dict(
                    kind=ln["kind"], doc=ln["doc"], student=ln["student"], je=ln["je"],
                    hit=[{"account": a, "net_cr": flt(v)} for a, v in hit]))
                continue
            k = comp["by_kind"].setdefault(ln["kind"], {"docs": 0, "rows": 0, "amount": 0.0})
            k["docs"] += 1
            for g in rows:
                if g.party and g.party != ln["student"]:
                    # Already named for someone else — never overwrite.
                    comp.setdefault("conflicts", []).append(
                        dict(gl=g.name, je=ln["je"], has=g.party, want=ln["student"]))
                    continue
                if g.party:
                    continue
                k["rows"] += 1
                k["amount"] += flt(g.credit) - flt(g.debit)
                comp["gl_rows"] += 1
                if not dry_run:
                    frappe.db.sql(
                        """UPDATE `tabGL Entry` SET party_type=%s, party=%s
                           WHERE name=%s AND IFNULL(party, '')=''""",
                        (PARTY_TYPE, ln["student"], g.name))
            jea = frappe.db.sql(
                """SELECT name FROM `tabJournal Entry Account`
                   WHERE parent=%s AND account=%s AND IFNULL(party, '')=''""",
                (ln["je"], control))
            comp["je_rows"] += len(jea)
            if not dry_run and jea:
                frappe.db.sql(
                    """UPDATE `tabJournal Entry Account` SET party_type=%s, party=%s
                       WHERE name IN %s""",
                    (PARTY_TYPE, ln["student"], tuple(r[0] for r in jea)))

        # Proof: what the receipt / refund / income lines say per student (as
        # tagged now, or as this run would tag them) vs the document formula.
        # Only those source vouchers count — a Student Journal Voucher posted
        # later is real ledger movement the documents never knew about, and
        # must not read as a mismatch on a re-run.
        docs = _document_balances(company)
        ledger = {}
        for p, v in (frappe.db.sql(
                """SELECT party, SUM(credit) - SUM(debit) FROM `tabGL Entry`
                   WHERE company=%(c)s AND party_type=%(pt)s AND is_cancelled=0
                     AND voucher_no IN %(j)s
                   GROUP BY party""",
                {"c": company, "pt": PARTY_TYPE, "j": tuple(jes)}) if jes else []):
            ledger[p] = flt(v)
        if dry_run:
            # Add what this run would attach (live rows only).
            live = {g.name for g in frappe.db.sql(
                """SELECT name FROM `tabGL Entry` WHERE company=%(c)s AND account=%(a)s
                   AND is_cancelled=0 AND voucher_no IN %(j)s""",
                {"c": company, "a": control, "j": tuple(jes)}, as_dict=True)} if jes else set()
            for ln in by_company[company]:
                for g in gl_by_je.get(ln["je"], []):
                    if not g.party and g.name in live:
                        ledger[ln["student"]] = flt(ledger.get(ln["student"])) + \
                            flt(g.credit) - flt(g.debit)
        for s in sorted(set(docs) | set(ledger)):
            if abs(flt(docs.get(s)) - flt(ledger.get(s))) > 0.5:
                comp["mismatches"].append(dict(student=s, documents=flt(docs.get(s)),
                                               ledger=flt(ledger.get(s))))
        comp["students"] = len(docs)
        comp["held_by_documents"] = flt(sum(docs.values()))
        comp["held_by_ledger"] = flt(sum(ledger.values()))

        # What stays on the account with nobody's name on it afterwards —
        # manual JEs / head-wise vouchers that never named a student.
        un = frappe.db.sql(
            """SELECT COUNT(*), COALESCE(SUM(credit) - SUM(debit), 0)
               FROM `tabGL Entry` gle
               LEFT JOIN `tabJournal Entry` je ON je.name=gle.voucher_no
                    AND gle.voucher_type='Journal Entry'
               WHERE gle.company=%(c)s AND gle.account=%(a)s AND gle.is_cancelled=0
                 AND IFNULL(gle.party, '')='' AND COALESCE(je.docstatus, 1)!=2
                 AND gle.voucher_no NOT IN %(j)s""",
            {"c": company, "a": control, "j": tuple(jes) or ("",)})
        comp["unattributed"] = {"rows": cint(un[0][0]), "net_cr": flt(un[0][1])}

        tot_gl += comp["gl_rows"]
        tot_jea += comp["je_rows"]
        report["companies"].append(comp)

    report["totals"] = {"gl_rows": tot_gl, "je_rows": tot_jea,
                        "source_vouchers": len(lines)}

    if not dry_run:
        frappe.db.set_single_value(SETTINGS, {
            "student_ledger_migrated": 1,
            "student_ledger_migrated_on": now_datetime(),
        })
        frappe.db.commit()
        report["tb_aggregate"] = _rebuild_tb_aggregate(sorted(by_company))
    return report


def _rebuild_tb_aggregate(companies):
    """Party columns on historic GL rows changed in place, so the monthly
    Trial Balance aggregate still holds those lines as party-less — and its
    nightly job only refreshes the last couple of months. Rebuild the
    companies it already holds. Runs after the commit: a failure here leaves
    the migration intact and is reported, not raised."""
    try:
        from dux_voucher.dux_voucher.api import tb_aggregate
        held = set(frappe.db.sql_list(
            "SELECT DISTINCT company FROM `tabDux TB Period Balance`"))
        touched = [c for c in companies if c in held]
        if not touched:
            return "not needed"
        tb_aggregate.rebuild(companies=touched)
        frappe.db.commit()
        return "rebuilt: " + ", ".join(touched)
    except Exception as e:
        frappe.db.rollback()
        return "FAILED — run tb_aggregate.rebuild for these companies by hand: " + str(e)


@frappe.whitelist(methods=["POST"])
def revert_migration():
    """Undo :func:`migrate` — take the student back off the historic lines
    and clear the flag, so balances come from the documents again.

    Refused once any Student Journal Voucher is submitted: those entries
    exist only in the ledger, and the document formula cannot see them.
    """
    frappe.only_for("System Manager")
    if frappe.db.exists("Student Journal Voucher", {"docstatus": 1}):
        frappe.throw(_("Student Journal Vouchers have been posted; the student "
                       "ledger can no longer be reverted."))
    jes = tuple({ln["je"] for ln in _source_lines()}) or ("",)
    frappe.db.sql(
        """UPDATE `tabGL Entry` SET party_type=NULL, party=NULL
           WHERE party_type=%(pt)s AND voucher_type='Journal Entry' AND voucher_no IN %(j)s""",
        {"pt": PARTY_TYPE, "j": jes})
    frappe.db.sql(
        """UPDATE `tabJournal Entry Account` SET party_type=NULL, party=NULL
           WHERE party_type=%(pt)s AND parent IN %(j)s""",
        {"pt": PARTY_TYPE, "j": jes})
    frappe.db.set_single_value(SETTINGS, {
        "student_ledger_migrated": 0,
        "student_ledger_migrated_on": None,
    })
    frappe.db.commit()
    return {"tb_aggregate": _rebuild_tb_aggregate(sorted(
        {ln["company"] for ln in _source_lines()}))}
