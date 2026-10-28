"""Student Journal Voucher — every non-cash entry against a student.

One voucher, one student. The purpose decides which side the student goes
on; the other side is either a list of ledgers or, for a transfer, the
inter-company account or another student:

    Purpose                       Student   Other side
    ----------------------------  --------  ---------------------------------
    Transfer to Institute         Dr        Branch & Division (institute)
                                            + the institute's books are posted
                                              in the same submit:
                                              Dr Branch & Division (this co.)
                                              Cr the ledger chosen there
    Fee Charged                   Dr        Cr income / deposit ledgers
    Fine / Penalty                Dr        Cr fine income ledgers
    Concession                    Cr        Dr concession ledger
    Transfer to Another Student   Dr        Cr the other student (same co.)
    Other Debit / Other Credit    Dr / Cr   any non-cash ledger

The student side is always the company's student ledger account
(``Admission/Registration Fee (Provisional) - {abbr}``) with the student as
party, so the student's balance is the GL sum of that party. Cash never
moves here: receipts and refunds stay with Student Fee Receipt / Refund.

A transfer can only move money the student actually has on hand (no
overdraft into another company's books); everything else may take the
student into debit — that is what raising a fee or a fine means.

Cancel-cascade in both directions reuses ``utils.on_journal_entry_cancel``:
both Journal Entries carry ``custom_source_voucher``, so cancelling either
one — including the institute's — cancels this voucher, which cancels the
other.
"""

import json

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, flt, fmt_money, getdate

from dux_voucher.dux_voucher.api.student_fee import get_admission_fee_account
from dux_voucher.dux_voucher.api.student_ledger import (
    PARTY_TYPE,
    get_student_balance,
    get_student_balances,
    is_migrated,
    require_company_access,
    require_migrated,
)
from dux_voucher.dux_voucher.api.utils import _safe_cancel, _submit_doc
from dux_voucher.dux_voucher.doctype.inter_company_transfer.inter_company_transfer import (
    get_branch_account,
)


TRANSFER_TO_INSTITUTE = "Transfer to Institute"
FEE_CHARGED = "Fee Charged"
FINE = "Fine / Penalty"
CONCESSION = "Concession"
TRANSFER_TO_STUDENT = "Transfer to Another Student"
OTHER_DEBIT = "Other Debit to Student"
OTHER_CREDIT = "Other Credit to Student"

PURPOSES = (TRANSFER_TO_INSTITUTE, FEE_CHARGED, FINE, CONCESSION,
            TRANSFER_TO_STUDENT, OTHER_DEBIT, OTHER_CREDIT)
TRANSFER_PURPOSES = (TRANSFER_TO_INSTITUTE, TRANSFER_TO_STUDENT)
CREDIT_PURPOSES = (CONCESSION, OTHER_CREDIT)

# Root types a ledger on the non-student side may have, per purpose. A
# concession is a reduction of fee income (or an expense); a fee charged
# is income or a refundable deposit (caution money); a fine is income.
# ``None`` = any root type.
ALLOWED_ROOT_TYPES = {
    FEE_CHARGED: ("Income", "Liability"),
    FINE: ("Income",),
    CONCESSION: ("Income", "Expense"),
    OTHER_DEBIT: None,
    OTHER_CREDIT: None,
}

# Never on the non-student side: Receivable/Payable lines need a party of
# their own, and real bank/cash accounts move money, which is what receipts
# and refunds are for. "Real" = an Asset typed Bank/Cash — the RGI chart has
# many INCOME heads typed "Cash" (Student ID Card Fine, Examination Fees …)
# and those are exactly what a fee or fine voucher credits.
PARTY_ACCOUNT_TYPES = ("Receivable", "Payable")
MONEY_ACCOUNT_TYPES = ("Bank", "Cash")

# What the receiving institute may be credited with on a transfer.
TRANSFER_IN_ROOT_TYPES = ("Asset", "Liability")

SETTINGS = "Student Fee Settings"


class StudentJournalVoucher(Document):

    # ── Lifecycle ────────────────────────────────────────────────────

    def insert(self, *args, **kwargs):
        """Scrub the links an amendment inherits from the cancelled voucher
        before Frappe's cancelled-link check runs — same reason as on the
        receipt and refund (``Document.insert`` validates links ahead of
        ``before_insert``)."""
        if self.amended_from:
            self.backend_je = None
            self.to_company_je = None
            self.is_posted = 0
        return super().insert(*args, **kwargs)

    def validate(self):
        require_migrated()
        self._validate_basic()
        self._validate_student(self.student, self.company, _("Student"))
        if self.purpose in TRANSFER_PURPOSES:
            self.set("heads", [])
            self._validate_transfer()
        else:
            self.to_company = self.to_account = self.to_student = None
            self.to_student_name = None
            self.from_branch_account = self.to_branch_account = None
            self.amount = 0
            self._validate_heads()
        self._snapshot_balance()

    def on_submit(self):
        self.db_set("backend_je", self._post_entry())
        if self.purpose == TRANSFER_TO_INSTITUTE:
            self.db_set("to_company_je", self._post_institute_entry())
        self.db_set("is_posted", 1)

    def on_cancel(self):
        # Institute side first: it is the one that depends on this side.
        if self.to_company_je:
            _safe_cancel("Journal Entry", self.to_company_je)
        if self.backend_je:
            _safe_cancel("Journal Entry", self.backend_je)
        self.db_set("is_posted", 0)

    # ── Validation ───────────────────────────────────────────────────

    @property
    def student_side(self):
        return "Cr" if self.purpose in CREDIT_PURPOSES else "Dr"

    def _validate_basic(self):
        if self.purpose not in PURPOSES:
            frappe.throw(_("Select a valid Purpose."))
        if not self.company:
            frappe.throw(_("Company is required."))
        if not self.posting_date:
            frappe.throw(_("Posting Date is required."))
        if not self.student:
            frappe.throw(_("Student is required."))
        self.control_account = get_admission_fee_account(self.company)

    def _validate_student(self, student, company, label):
        st = frappe.db.get_value(
            "Student", student, ["company", "is_disabled", "student_name"], as_dict=True)
        if not st:
            frappe.throw(_("{0} {1} does not exist.").format(label, student))
        if st.company != company:
            frappe.throw(_("{0} {1} ({2}) belongs to {3}, not {4}.")
                         .format(label, st.student_name or student, student,
                                 st.company, company))
        if cint(st.is_disabled):
            frappe.throw(_("{0} {1} is disabled.").format(label, st.student_name or student))

    def _validate_transfer(self):
        amount = flt(self.amount)
        if amount <= 0:
            frappe.throw(_("Amount must be greater than zero."))
        self.total_amount = amount

        if self.purpose == TRANSFER_TO_INSTITUTE:
            self._validate_institute()
        else:
            if not self.to_student:
                frappe.throw(_("Select the student the amount moves to."))
            if self.to_student == self.student:
                frappe.throw(_("A student cannot transfer to themselves."))
            self._validate_student(self.to_student, self.company, _("To Student"))
            self.to_company = self.to_account = None
            self.from_branch_account = self.to_branch_account = None

        # Only money that is actually held can move — a transfer that took
        # the student into debit would hand the institute money nobody paid.
        held = get_student_balance(self.student, self.company)
        if amount > held + 0.005:
            frappe.throw(_(
                "Only {0} is held for {1}; {2} cannot be transferred. Raise or "
                "collect the difference first, or transfer a smaller amount.")
                .format(_money(max(held, 0), self.company),
                        self.student_name or self.student, _money(amount, self.company)))

    def _validate_institute(self):
        if not self.to_company:
            frappe.throw(_("Select the institute the fee is transferred to."))
        if self.to_company == self.company:
            frappe.throw(_("The institute must be a different company. To move "
                           "money between two students here, use Transfer to "
                           "Another Student."))
        if cint(frappe.db.get_value("Company", self.to_company, "is_group")):
            frappe.throw(_("{0} is a group company — pick the institute itself.")
                         .format(self.to_company))
        if not self.to_account:
            frappe.throw(_("Select the ledger credited at {0}.").format(self.to_company))

        meta = _account_meta(self.to_account)
        if meta.company != self.to_company:
            frappe.throw(_("Ledger {0} belongs to {1}, not {2}.")
                         .format(self.to_account, meta.company, self.to_company))
        _check_postable(meta, _("Ledger Credited at Institute"))
        # The institute has not earned the fee yet — it is an advance against
        # the demand its campus system (CyberVidya) raises. Crediting income
        # here would count the fee twice once that demand posts.
        if meta.root_type not in TRANSFER_IN_ROOT_TYPES:
            frappe.throw(_(
                "{0} is an {1} ledger. A transferred fee is not income yet at "
                "the institute — credit its student receivable or fees-received-"
                "in-advance ledger (an Asset or Liability).")
                .format(self.to_account, meta.root_type))

        # Crediting the institute's own student ledger needs the student as
        # registered there; anything else is a pooled ledger with no party.
        to_control = _control_account_or_none(self.to_company)
        if self.to_account == to_control:
            if not self.to_student:
                frappe.throw(_(
                    "{0} is the student ledger of {1}. Select the student as "
                    "registered at {1} in <strong>To Student</strong>.")
                    .format(self.to_account, self.to_company))
            self._validate_student(self.to_student, self.to_company, _("To Student"))
        else:
            self.to_student = None
            self.to_student_name = None

        self.from_branch_account = get_branch_account(self.company, self.to_company)
        self.to_branch_account = get_branch_account(self.to_company, self.company)
        if self.to_account == self.to_branch_account:
            frappe.throw(_("The ledger credited at the institute cannot be its "
                           "inter-company account for {0}.").format(self.company))

    def _validate_heads(self):
        if not self.heads:
            frappe.throw(_("Add at least one ledger row."))
        allowed = ALLOWED_ROOT_TYPES.get(self.purpose)
        total = 0.0
        for row in self.heads:
            if not row.account:
                frappe.throw(_("Row {0}: Ledger is required.").format(row.idx))
            if flt(row.amount) <= 0:
                frappe.throw(_("Row {0}: Amount must be greater than zero.").format(row.idx))
            meta = _account_meta(row.account)
            if meta.company != self.company:
                frappe.throw(_("Row {0}: Ledger {1} belongs to {2}, not {3}.")
                             .format(row.idx, row.account, meta.company, self.company))
            _check_postable(meta, _("Row {0}").format(row.idx))
            if row.account == self.control_account:
                frappe.throw(_("Row {0}: {1} is the student ledger itself — choose "
                               "the ledger on the other side of the entry.")
                             .format(row.idx, row.account))
            if allowed and meta.root_type not in allowed:
                frappe.throw(_("Row {0}: a {1} entry takes {2} ledgers; {3} is {4}.")
                             .format(row.idx, self.purpose, _(" / ").join(allowed),
                                     row.account, meta.root_type))
            total += flt(row.amount)
        self.total_amount = flt(total)

    def _snapshot_balance(self):
        """Balance before and after this voucher, for the form and the print.
        Read again at submit (validate runs then too), so the printed
        figures are the ones true at posting time."""
        before = get_student_balance(self.student, self.company)
        sign = 1 if self.student_side == "Cr" else -1
        self.balance_before = flt(before)
        self.balance_after = flt(before + sign * flt(self.total_amount))

    # ── Posting ──────────────────────────────────────────────────────

    def _new_je(self, company, remark):
        je = frappe.new_doc("Journal Entry")
        je.voucher_type = "Journal Entry"
        je.company = company
        je.posting_date = self.posting_date
        je.user_remark = remark
        je.custom_source_voucher_doctype = self.doctype
        je.custom_source_voucher = self.name
        return je

    def _student_line(self, je, student, side, amount, remark=None):
        je.append("accounts", {
            "account": get_admission_fee_account(self.company),
            "party_type": PARTY_TYPE,
            "party": student,
            "debit_in_account_currency": amount if side == "Dr" else 0,
            "credit_in_account_currency": amount if side == "Cr" else 0,
            "user_remark": remark,
        })

    def _post_entry(self):
        amount = flt(self.total_amount)
        je = self._new_je(self.company, self.narration())
        self._student_line(je, self.student, self.student_side, amount)

        if self.purpose == TRANSFER_TO_INSTITUTE:
            je.append("accounts", {
                "account": self.from_branch_account,
                "credit_in_account_currency": amount,
                "debit_in_account_currency": 0,
                "user_remark": _("Fee transferred to {0}").format(self.to_company),
            })
        elif self.purpose == TRANSFER_TO_STUDENT:
            self._student_line(je, self.to_student, "Cr", amount,
                               _("From {0}").format(self.student_name or self.student))
        else:
            other = "Cr" if self.student_side == "Dr" else "Dr"
            for row in self.heads:
                je.append("accounts", {
                    "account": row.account,
                    "debit_in_account_currency": flt(row.amount) if other == "Dr" else 0,
                    "credit_in_account_currency": flt(row.amount) if other == "Cr" else 0,
                    "user_remark": row.remarks,
                })
        _submit_doc(je)
        return je.name

    def _post_institute_entry(self):
        """The receiving institute's side of a transfer, posted in the same
        submit: Dr its inter-company ledger for this company, Cr the ledger
        chosen for it (with the student as party when that is the
        institute's own student ledger)."""
        amount = flt(self.total_amount)
        je = self._new_je(self.to_company, _(
            "Fee of {0} ({1}) received by transfer from {2} — {3}").format(
                self.student_name or self.student, self.course or "",
                self.company, self.name))
        je.append("accounts", {
            "account": self.to_branch_account,
            "debit_in_account_currency": amount,
            "credit_in_account_currency": 0,
        })
        line = {
            "account": self.to_account,
            "debit_in_account_currency": 0,
            "credit_in_account_currency": amount,
            "user_remark": _("Fee of {0}").format(self.student_name or self.student),
        }
        if self.to_student:
            line.update({"party_type": PARTY_TYPE, "party": self.to_student})
        je.append("accounts", line)
        _submit_doc(je)
        return je.name

    def narration(self):
        if (self.remarks or "").strip():
            return self.remarks.strip()
        who = self.student_name or self.student
        heads = ", ".join(r.account.rsplit(" - ", 1)[0] for r in (self.heads or []))
        if self.purpose == TRANSFER_TO_INSTITUTE:
            return _("Fee of {0} transferred to {1}").format(who, self.to_company)
        if self.purpose == TRANSFER_TO_STUDENT:
            return _("Amount transferred from {0} to {1}").format(
                who, self.to_student_name or self.to_student)
        if self.purpose == FEE_CHARGED:
            return _("Fee charged to {0} — {1}").format(who, heads)
        if self.purpose == FINE:
            return _("Fine debited to {0} — {1}").format(who, heads)
        if self.purpose == CONCESSION:
            return _("Fee concession to {0} — {1}").format(who, heads)
        return _("Student journal — {0} — {1}").format(who, heads)


# =====================================================================
# Helpers
# =====================================================================

def _money(v, company):
    cur = frappe.get_cached_value("Company", company, "default_currency") or "INR"
    return fmt_money(v, currency=cur)


def _account_meta(account):
    meta = frappe.db.get_value(
        "Account", account,
        ["name", "company", "is_group", "disabled", "account_type", "root_type"],
        as_dict=True)
    if not meta:
        frappe.throw(_("Ledger {0} does not exist.").format(account))
    return meta


def _check_postable(meta, label):
    if cint(meta.is_group):
        frappe.throw(_("{0}: {1} is a group — pick a ledger under it.").format(label, meta.name))
    if cint(meta.disabled):
        frappe.throw(_("{0}: {1} is disabled.").format(label, meta.name))
    if meta.account_type in PARTY_ACCOUNT_TYPES:
        frappe.throw(_(
            "{0}: {1} is a {2} ledger and would need a party of its own — "
            "pick a ledger without one.").format(label, meta.name, meta.account_type))
    if meta.account_type in MONEY_ACCOUNT_TYPES and meta.root_type == "Asset":
        frappe.throw(_(
            "{0}: {1} is a {2} account. Money received or paid goes through "
            "Student Fee Receipt / Refund; this voucher only moves amounts "
            "between ledgers.").format(label, meta.name, meta.account_type))


def _control_account_or_none(company):
    try:
        return get_admission_fee_account(company)
    except frappe.ValidationError:
        frappe.clear_last_message()
        return None


def _transfer_default_account(to_company):
    return frappe.db.get_value(
        "Student Transfer Account",
        {"parent": SETTINGS, "parenttype": SETTINGS, "company": to_company},
        "account")


# =====================================================================
# Form helpers
# =====================================================================

@frappe.whitelist()
def get_context(company, student=None, to_company=None):
    """Everything the form shows before posting: the student ledger, the
    student's balance, and for a transfer the default ledger and both
    inter-company accounts (or why they cannot be resolved)."""
    frappe.has_permission("Student Journal Voucher", "read", throw=True)
    require_company_access(company)
    out = {"migrated": is_migrated(), "account": None, "balance": None}
    if company:
        out["account"] = _control_account_or_none(company)
    if company and student and out["migrated"]:
        out["balance"] = get_student_balance(student, company)
    if company and to_company and to_company != company:
        out["to_account_default"] = _transfer_default_account(to_company)
        out["to_control_account"] = _control_account_or_none(to_company)
        try:
            out["from_branch_account"] = get_branch_account(company, to_company)
            out["to_branch_account"] = get_branch_account(to_company, company)
        except frappe.ValidationError as e:
            frappe.clear_last_message()
            out["branch_error"] = str(e)
    return out


# =====================================================================
# Bulk creation — one voucher per student, created as drafts
# =====================================================================

def _parse(params):
    p = frappe._dict(json.loads(params) if isinstance(params, str) else (params or {}))
    if p.purpose not in PURPOSES:
        frappe.throw(_("Select a valid Purpose."))
    if not p.company:
        frappe.throw(_("Company is required."))
    p.heads = [frappe._dict(h) for h in (p.heads or []) if h.get("account") and flt(h.get("amount")) > 0]
    return p


def _indian_fy_bounds(d):
    d = getdate(d)
    start_year = d.year if d.month >= 4 else d.year - 1
    return getdate(f"{start_year}-04-01"), getdate(f"{start_year + 1}-03-31")


@frappe.whitelist()
def bulk_preview(params):
    """Which students a bulk run would create vouchers for, and for how much.

    Transfers default to each student's full balance and skip anyone with
    nothing held. Fee / fine / concession runs use the same ledgers and
    amounts for every student, and by default skip students who already
    have a voucher of that purpose in the same financial year (Apr–Mar), so
    a second run cannot charge the hostel fee twice.
    """
    frappe.has_permission("Student Journal Voucher", "create", throw=True)
    require_migrated()
    p = _parse(params)
    require_company_access(p.company)

    filters = {"company": p.company, "is_disabled": 0}
    if p.course:
        filters["course"] = p.course
    # An explicit selection (the ticks in the Bulk Create preview) restricts
    # the run — and an empty selection means nobody, never "everybody".
    if p.get("students") is not None:
        if not p.students:
            return {"rows": [], "eligible": 0, "total": 0.0}
        filters["name"] = ["in", list(p.students)]
    students = frappe.get_all("Student", filters=filters,
                              fields=["name", "student_name", "course"],
                              order_by="student_name asc", limit_page_length=0)
    balances = get_student_balances([s.name for s in students], p.company)

    # A draft of the same purpose is always a duplicate (a second click
    # before the first batch was submitted — drafts do not move the balance,
    # so the transfer cap cannot catch it). Submitted ones in the same
    # financial year are skipped too unless the operator unticks the box.
    existing = set(frappe.get_all(
        "Student Journal Voucher",
        filters={"company": p.company, "purpose": p.purpose, "docstatus": 0},
        pluck="student"))
    if cint(p.get("skip_existing", 1)):
        fy_start, fy_end = _indian_fy_bounds(p.posting_date or getdate())
        existing |= set(frappe.get_all(
            "Student Journal Voucher",
            filters={"company": p.company, "purpose": p.purpose, "docstatus": 1,
                     "posting_date": ["between", [fy_start, fy_end]]},
            pluck="student"))

    fixed = flt(p.amount)
    heads_total = sum(flt(h.amount) for h in p.heads)
    rows = []
    for s in students:
        bal = flt(balances.get(s.name))
        row = {"student": s.name, "student_name": s.student_name, "course": s.course,
               "balance": bal, "amount": 0.0, "ok": 1, "note": ""}
        if p.purpose in TRANSFER_PURPOSES:
            amt = fixed if p.amount_mode == "Fixed amount" else bal
            row["amount"] = flt(amt)
            if s.name in existing:
                row.update(ok=0, note=_("Already has a {0} voucher").format(p.purpose))
            elif bal <= 0.005:
                row.update(ok=0, note=_("Nothing held"))
            elif amt <= 0:
                row.update(ok=0, note=_("No amount"))
            elif amt > bal + 0.005:
                row.update(ok=0, note=_("Only {0} held").format(_money(bal, p.company)))
        else:
            row["amount"] = heads_total
            if s.name in existing:
                row.update(ok=0, note=_("Already has a {0} voucher this year").format(p.purpose))
        rows.append(row)
    return {"rows": rows, "eligible": sum(r["ok"] for r in rows),
            "total": flt(sum(r["amount"] for r in rows if r["ok"]))}


@frappe.whitelist()
def bulk_create(params):
    """Create one DRAFT voucher per eligible student from :func:`bulk_preview`.

    Drafts, not submitted vouchers: each one is reviewed (or bulk-submitted
    from the list view, which runs in the background for large batches) so
    a wrong ledger or amount is caught before anything posts. A student
    that fails validation is reported and skipped; the rest still go in.
    """
    frappe.has_permission("Student Journal Voucher", "create", throw=True)
    p = _parse(params)
    if p.purpose == TRANSFER_TO_STUDENT:
        frappe.throw(_("Transfer to Another Student is one pair at a time — "
                       "create it from a single voucher."))
    if p.get("students") is not None and not p.students:
        frappe.throw(_("No students are selected."))
    preview = bulk_preview(params)
    created, failed = [], []
    for r in preview["rows"]:
        if not r["ok"]:
            continue
        doc = frappe.new_doc("Student Journal Voucher")
        doc.update({
            "company": p.company,
            "posting_date": p.posting_date or getdate(),
            "purpose": p.purpose,
            "student": r["student"],
            "remarks": p.remarks,
        })
        if p.naming_series:
            doc.naming_series = p.naming_series
        if p.purpose == TRANSFER_TO_INSTITUTE:
            doc.update({"to_company": p.to_company, "to_account": p.to_account,
                        "amount": r["amount"]})
        else:
            for h in p.heads:
                doc.append("heads", {"account": h.account, "amount": flt(h.amount),
                                     "remarks": h.get("remarks")})
        try:
            frappe.db.savepoint("sjv_bulk")
            doc.insert()
            created.append({"name": doc.name, "student": r["student"],
                            "student_name": r["student_name"], "amount": doc.total_amount})
        except Exception as e:
            frappe.db.rollback(save_point="sjv_bulk")
            frappe.clear_last_message()
            failed.append({"student": r["student"], "student_name": r["student_name"],
                           "error": frappe.utils.strip_html(str(e))})
    return {"created": created, "failed": failed}
