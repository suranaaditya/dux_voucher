"""Set a project on a Purchase Order — and on everything already made from it.

The gap this closes
-------------------
A PO is raised, approved, received and billed, and only then does someone
notice it never named its project. ERPNext offers no way back:

* ``Purchase Order`` and ``Purchase Receipt`` lock ``project`` on submit
  (``allow_on_submit = 0`` on header and item rows alike);
* ``Purchase Invoice`` and ``Payment Entry`` do allow it, but saving the edit
  triggers a ledger repost that ``Repost Accounting Ledger Settings`` must
  whitelist — on this site that list is empty, so the save is refused;
* nothing carries an edit from one document to the next.

The Capital Projects dashboard reads Committed from PO lines and Invoiced /
Paid from ``GL Entry.project``, so a late tag has to reach the ledger too.

What one run does
-----------------
Each PO line is planned together with the GRN and invoice lines made from
it, by the links ERPNext itself stores:

    PO line ─► GRN line (purchase_order_item)
            ─► invoice line (po_detail, or pr_detail of those GRN lines)

That CHAIN moves as one or not at all. ERPNext re-checks on every later
document that a GRN / invoice line's project equals the line it came from,
so a chain left half-moved (a GRN line kept on another project, or frozen in
a closed period, under a PO line that moved) would make the next invoice or
return impossible to save. A chain with any link on a different project
(unless ``overwrite``), in a frozen / closed period, or not readable by the
user is held back whole and reported.

"On a project" means the EFFECTIVE project: the line's own, else its
document's header — what the dashboard (``COALESCE(line, header)``) and the
posted ledger already treat it as.

Then, per document, header and ledger follow:

* the header takes the project when every line now belongs to it;
* a GRN's GL rows carry only its HEADER project (``add_gl_entry`` never
  passes the line's), so they move only with the header; its stock ledger
  rows point at their line and are tagged per line;
* an invoice wholly on one project has every ledger row tagged. A MIXED one
  has its ledger re-derived in memory by ERPNext's own ``get_gl_entries``
  and paired row-for-row with what is posted — invoice and GRN ledger rows
  carry no ``voucher_detail_no`` (0 of 960 / 791 on production), so this is
  the only exact mapping. Unpaired → left and reported;
* payments whose EVERY reference belongs to the project, and journal rows
  paying such an invoice whose own GL row can be identified, follow.

**Only the project column changes — no amount, account, party or date.**
Every changed document gets a timeline comment naming who, when, the POs
that reached it, and the project before and after.
"""

import re
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import cint, flt, get_datetime, getdate, now_datetime


# Rewriting the project on ledger entries is accounts work; Projects Manager
# alone does not reach the books.
ROLES = {"System Manager", "Accounts Manager"}
MAX_ORDERS = 500

PO, PR, PI, PE, JE = ("Purchase Order", "Purchase Receipt", "Purchase Invoice",
                      "Payment Entry", "Journal Entry")
ITEM_TABLE = {PO: "Purchase Order Item", PR: "Purchase Receipt Item",
              PI: "Purchase Invoice Item"}
KIND = {PO: "Order", PR: "Receipt", PI: "Invoice", PE: "Payment", JE: "Journal"}

# What get_gl_entries may raise on a document it cannot re-derive; anything
# else (a deadlock, a lost savepoint) must abort the run, not be swallowed.
_REDERIVE_ERRORS = (frappe.ValidationError, TypeError, AttributeError, KeyError,
                    ValueError, IndexError, ZeroDivisionError)


# =====================================================================
# Endpoints
# =====================================================================

def require_access():
    if set(frappe.get_roles()) & ROLES:
        return
    frappe.throw(_("Setting a project on submitted documents needs the Accounts "
                   "Manager role."), frappe.PermissionError)


@frappe.whitelist()
def preview(rows, overwrite=0):
    """What a run would change. Writes nothing."""
    require_access()
    return _report(_plan(_parse_rows(rows), cint(overwrite)))


@frappe.whitelist(methods=["POST"])
def apply(rows, overwrite=0):
    """Re-plan from the database as it stands now, then write it in one
    transaction. Any failure rolls back the whole run."""
    require_access()
    plan = _plan(_parse_rows(rows), cint(overwrite))
    try:
        _execute(plan)
    except Exception:
        frappe.db.rollback()
        raise
    _refresh_project_costing(plan)
    out = _report(plan)
    out["applied"] = True
    return out


@frappe.whitelist(methods=["POST"])
def read_sheet(file_url):
    """Rows ``{purchase_order, project, supplier?, amount?}`` from an uploaded
    xlsx / csv — the layout the site teams already send (PO Number, Vendor
    Name, PO Amount, Project Name), found by header, not by position. The
    uploaded file is deleted once read."""
    require_access()
    # Only the sheet this user has just uploaded: the file is deleted after
    # reading, so anything looser would let a caller delete someone else's
    # attachment by naming its URL.
    f = frappe.db.get_value(
        "File", {"file_url": file_url, "owner": frappe.session.user, "is_folder": 0},
        ["name", "file_name", "attached_to_doctype", "creation"], as_dict=True)
    if not f or f.attached_to_doctype or \
            (now_datetime() - get_datetime(f.creation)).total_seconds() > 3600:
        frappe.throw(_("Upload the sheet again — only a file you have just uploaded can be read here."))
    f = frappe.get_doc("File", f.name)
    name = (f.file_name or file_url).lower()
    try:
        content = f.get_content()
        if name.endswith(".xlsx"):
            from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file
            table = read_xlsx_file_from_attached_file(fcontent=content)
        elif name.endswith(".csv"):
            from frappe.utils.csvutils import read_csv_content
            table = read_csv_content(content)
        else:
            frappe.throw(_("Upload an .xlsx or .csv file."))
    finally:
        frappe.delete_doc("File", f.name, ignore_permissions=True, force=True)
    return parse_table(table)


# =====================================================================
# Sheet parsing (pure)
# =====================================================================

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def detect_columns(header):
    """Map a header row to column indexes. PO: 'PO Number', 'PO No', 'Purchase
    Order'. Project: anything mentioning project. Supplier / amount are
    optional and only used to cross-check the sheet against the PO."""
    cols = {}
    for i, h in enumerate(header or []):
        n = _norm(h)
        if not n:
            continue
        if "po" not in cols and (n in ("purchaseorder", "purchaseorderno", "purchaseordernumber")
                                 or (n.startswith("po") and ("number" in n or n in ("pono", "po")))):
            cols["po"] = i
        elif "project" not in cols and "project" in n:
            cols["project"] = i
        elif "supplier" not in cols and ("vendor" in n or "supplier" in n or n == "party"):
            cols["supplier"] = i
        elif "amount" not in cols and ("amount" in n or "value" in n or "total" in n):
            cols["amount"] = i
    return cols


def parse_table(table):
    """``{"rows": [...], "header_row": n}`` — the header is searched for in the
    first ten rows, so a title line above it is fine."""
    table = table or []
    for h_idx, header in enumerate(table[:10]):
        cols = detect_columns(header)
        if "po" in cols and "project" in cols:
            break
    else:
        frappe.throw(_("Could not find a PO Number column and a Project column in "
                       "the first ten rows of the sheet."))
    rows = []
    for n, r in enumerate(table[h_idx + 1:], start=h_idx + 2):
        def cell(key):
            i = cols.get(key)
            return r[i] if i is not None and i < len(r) else None
        po = str(cell("po") or "").strip()
        if not po:
            continue
        row = {"purchase_order": po, "project": str(cell("project") or "").strip(), "line": n}
        if cell("supplier"):
            row["supplier"] = str(cell("supplier")).strip()
        if cell("amount") not in (None, ""):
            try:
                row["amount"] = flt(str(cell("amount")).replace(",", ""))
            except Exception:
                pass
        rows.append(row)
    return {"rows": rows, "header_row": h_idx + 1}


# =====================================================================
# Planning — read only
# =====================================================================

def _parse_rows(rows):
    rows = frappe.parse_json(rows) if isinstance(rows, str) else rows
    out = []
    for r in rows or []:
        r = frappe._dict(r)
        po = (r.purchase_order or "").strip()
        if po:
            out.append(frappe._dict(purchase_order=po, project=(r.project or "").strip(),
                                    supplier=r.get("supplier"), amount=r.get("amount"),
                                    line=r.get("line")))
    if not out:
        frappe.throw(_("No Purchase Orders to tag."))
    if len(out) > MAX_ORDERS:
        frappe.throw(_("At most {0} Purchase Orders per run.").format(MAX_ORDERS))
    return out


def resolve_project(value):
    """The stored name of a Project given by ID (PROJ-0012) or by its full
    name (GHREMFP - New Workshop Building), case and spacing ignored. Always
    the stored spelling — a sheet's 'proj-0001' must not reach the ledger."""
    value = (value or "").strip()
    if not value:
        return None
    hit = frappe.db.get_value("Project", value, "name")
    if hit:
        return hit
    hit = frappe.db.sql(
        """SELECT name FROM `tabProject`
           WHERE LOWER(TRIM(REPLACE(project_name, '  ', ' '))) = LOWER(TRIM(REPLACE(%s, '  ', ' ')))
           LIMIT 2""", value)
    return hit[0][0] if len(hit) == 1 else None


class _Plan:
    def __init__(self, overwrite):
        self.overwrite = overwrite
        self.orders = []            # one dict per input row
        self.targets = {}           # po -> project
        self.lines = {}             # (child_dt, name) -> change dict
        self.docs = {}              # (dt, name) -> document state
        self.blocked = []           # PO lines held back, with reasons
        self.payments = []          # Payment Entry changes
        self.journal_rows = []      # Journal Entry Account changes
        self.skipped = []           # {doctype, name, reason}
        self.conflicts = []         # header conflicts {doctype, name, has, want}
        self.warnings = []          # {purchase_order, message}
        self.projects = set()       # projects whose costing needs a refresh
        self._info = {}

    def info(self, dt, name):
        """Header facts of a document, read once: company, docstatus,
        project, date, why its ledger is locked, and whether the user may
        read it."""
        key = (dt, name)
        if key not in self._info:
            date_field = "transaction_date" if dt == PO else "posting_date"
            fields = ["company", "docstatus", date_field]
            if frappe.get_meta(dt).has_field("project"):     # Journal Entry has none
                fields.append("project")
            d = frappe.db.get_value(dt, name, fields, as_dict=True) or frappe._dict()
            date = d.get(date_field)
            closed = None
            if dt != PO and d.get("docstatus") == 1:
                closed = _closed_reason(d.company, date, dt)
            self._info[key] = frappe._dict(
                company=d.get("company"), docstatus=d.get("docstatus"),
                project=d.get("project") or "", date=str(date) if date else None,
                closed=closed, readable=bool(frappe.has_permission(dt, "read", doc=name)))
        return self._info[key]

    def doc(self, dt, name):
        return self.docs.setdefault((dt, name), {"pos": set(), "changed": 0})

    def skip(self, dt, name, reason):
        self.skipped.append({"doctype": dt, "name": name, "reason": reason})


def _plan(rows, overwrite):
    plan = _Plan(overwrite)
    _resolve_orders(plan, rows)

    # 1. Each PO line with everything made from it, as one chain.
    for po, target in plan.targets.items():
        _plan_order(plan, po, target)

    # 2. Each touched document: blank lines inherit their own PO's project,
    #    then header and ledger follow from the final lines.
    for (dt, name), state in list(plan.docs.items()):
        _settle_document(plan, dt, name, state)

    # Mixed invoices: pair their ledger now, so the preview already says
    # which ones will be left for a repost.
    for (dt, name), state in plan.docs.items():
        if state.get("ledger") == "match":
            state["pairs"] = _mixed_pairs(plan, dt, name, state)
            if state["pairs"] is None:
                state["ledger"] = "unmatched"

    # 3. Payments and journal payments — only once the invoices are settled.
    _plan_payments(plan)
    _plan_journal_rows(plan)
    return plan


def _resolve_orders(plan, rows):
    projects_by_po = defaultdict(set)
    for r in rows:
        projects_by_po[r.purchase_order].add(resolve_project(r.project) or ("?" + (r.project or "")))
    for r in rows:
        entry = {"purchase_order": r.purchase_order, "project_input": r.project, "line": r.line,
                 "status": "ready", "error": None}
        plan.orders.append(entry)
        # Permission first: nothing about a PO the user may not read leaves here.
        if not frappe.db.exists(PO, r.purchase_order) or \
                not frappe.has_permission(PO, "read", doc=r.purchase_order):
            entry.update(status="error", error=_("No such Purchase Order, or no access to it"))
            continue
        po = frappe.db.get_value(PO, r.purchase_order,
                                 ["name", "company", "supplier", "supplier_name", "docstatus",
                                  "grand_total", "transaction_date"], as_dict=True)
        entry.update(company=po.company, supplier=po.supplier_name or po.supplier,
                     grand_total=flt(po.grand_total), transaction_date=str(po.transaction_date))
        if po.docstatus == 2:
            entry.update(status="error", error=_("Cancelled"))
            continue
        if len(projects_by_po[po.name]) > 1:
            # Never guess which row the sheet meant.
            entry.update(status="error", error=_("Listed more than once with different projects"))
            continue
        project = resolve_project(r.project)
        if not project:
            entry.update(status="error", error=_("Project '{0}' not found").format(r.project or ""))
            continue
        p = frappe.db.get_value("Project", project, ["project_name", "company", "status"], as_dict=True)
        entry.update(project=project, project_name=p.project_name)
        if p.company and p.company != po.company:
            entry.update(status="error",
                         error=_("Project belongs to {0}, the PO to {1}").format(p.company, po.company))
            continue
        if p.status == "Cancelled":
            entry.update(status="error", error=_("Project is cancelled"))
            continue
        if po.name in plan.targets:
            entry.update(status="duplicate")
            continue
        # Cross-check the sheet's own columns against the PO — a warning, never a block.
        if r.amount and abs(flt(r.amount) - flt(po.grand_total)) > 1:
            plan.warnings.append({"purchase_order": po.name, "message": _(
                "Sheet amount {0} differs from the PO total {1}").format(
                    frappe.format_value(r.amount, {"fieldtype": "Currency"}),
                    frappe.format_value(po.grand_total, {"fieldtype": "Currency"}))})
        if r.supplier and not _names_match(r.supplier, po.supplier_name or po.supplier):
            plan.warnings.append({"purchase_order": po.name, "message": _(
                "Sheet vendor '{0}' differs from the PO supplier '{1}'").format(
                    r.supplier, po.supplier_name or po.supplier)})
        plan.targets[po.name] = project
        plan.projects.add(project)


def _names_match(a, b):
    a, b = _norm(a), _norm(b)
    return bool(a and b and (a in b or b in a))


def _plan_order(plan, po, target):
    po_lines = frappe.db.sql(
        """SELECT name, idx, item_code, IFNULL(project, '') AS project
           FROM `tabPurchase Order Item` WHERE parent=%s AND parenttype=%s ORDER BY idx""",
        (po, PO), as_dict=True)
    names = tuple(d.name for d in po_lines) or ("",)
    pr_lines = frappe.db.sql(
        """SELECT pri.name, pri.parent, IFNULL(pri.project, '') AS project, pri.purchase_order_item
           FROM `tabPurchase Receipt Item` pri
           JOIN `tabPurchase Receipt` pr ON pr.name = pri.parent
           WHERE pr.docstatus < 2 AND pri.purchase_order_item IN %(i)s""", {"i": names}, as_dict=True)
    pr_to_po_line = {d.name: d.purchase_order_item for d in pr_lines}
    pi_lines = frappe.db.sql(
        """SELECT pii.name, pii.parent, IFNULL(pii.project, '') AS project,
                  IFNULL(pii.po_detail, '') AS po_detail, IFNULL(pii.pr_detail, '') AS pr_detail
           FROM `tabPurchase Invoice Item` pii
           JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
           WHERE pi.docstatus < 2 AND (pii.po_detail IN %(i)s OR pii.pr_detail IN %(r)s)""",
        {"i": names, "r": tuple(pr_to_po_line) or ("",)}, as_dict=True)

    chains = defaultdict(list)
    for d in pr_lines:
        chains[d.purchase_order_item].append((PR, d.parent, d.name, d.project))
    for d in pi_lines:
        line = d.po_detail if d.po_detail in names else pr_to_po_line.get(d.pr_detail)
        if line:
            chains[line].append((PI, d.parent, d.name, d.project))

    for L in po_lines:
        members = [(PO, po, L.name, L.project)] + chains.get(L.name, [])
        reasons = []
        for dt, parent, _child, raw in members:
            inf = plan.info(dt, parent)
            effective = raw or inf.project
            if effective and effective != target and not plan.overwrite:
                reasons.append(_("{0} {1} is on {2}").format(_(KIND[dt]), parent, _pname(effective)))
            if inf.closed:
                reasons.append(_("{0} {1}: {2}").format(_(KIND[dt]), parent, inf.closed))
            if not inf.readable:
                reasons.append(_("no access to {0} {1}").format(_(KIND[dt]), parent))
        if reasons:
            plan.blocked.append({"purchase_order": po, "line": L.idx, "item_code": L.item_code,
                                 "reasons": list(dict.fromkeys(reasons))})
            continue
        for dt, parent, child, raw in members:
            state = plan.doc(dt, parent)
            state["pos"].add(po)
            if raw == target:
                continue
            key = (ITEM_TABLE[dt], child)
            change = plan.lines.setdefault(key, {"doctype": dt, "parent": parent, "from": raw,
                                                 "to": target, "pos": set()})
            change["pos"].add(po)
            effective = raw or plan.info(dt, parent).project
            if effective and effective != target:
                plan.projects.add(effective)


def _own_po_projects(dt, name):
    """``{line: (po_line, project)}`` for the lines of a GRN / invoice, with
    the project of the PO line each came from as it stands in the database
    (line, else PO header)."""
    if dt == PR:
        rows = frappe.db.sql(
            """SELECT pri.name, poi.name, COALESCE(NULLIF(poi.project, ''), po.project, ''), ''
               FROM `tabPurchase Receipt Item` pri
               JOIN `tabPurchase Order Item` poi ON poi.name = pri.purchase_order_item
               JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1
               WHERE pri.parent = %s""", name)
    else:
        rows = frappe.db.sql(
            """SELECT pii.name, poi.name, COALESCE(NULLIF(poi.project, ''), po.project, ''),
                      IFNULL(pii.pr_detail, '')
               FROM `tabPurchase Invoice Item` pii
               LEFT JOIN `tabPurchase Receipt Item` pri ON pri.name = pii.pr_detail
               JOIN `tabPurchase Order Item` poi
                    ON poi.name = COALESCE(NULLIF(pii.po_detail, ''), pri.purchase_order_item)
               JOIN `tabPurchase Order` po ON po.name = poi.parent AND po.docstatus = 1
               WHERE pii.parent = %s""", name)
    return {line: (po_line, project, pr_line) for line, po_line, project, pr_line in rows}


def _planned(plan, child_dt, child, current):
    change = plan.lines.get((child_dt, child))
    return change["to"] if change else (current or "")


def _settle_document(plan, dt, name, state):
    inf = plan.info(dt, name)
    header = inf.project
    state.update(company=inf.company, docstatus=inf.docstatus, header_from=header,
                 date=inf.date)
    child_dt = ITEM_TABLE[dt]
    lines = frappe.db.sql(
        f"SELECT name, IFNULL(project, '') FROM `tab{child_dt}` WHERE parent=%s AND parenttype=%s",
        (name, dt))
    own = _own_po_projects(dt, name) if dt != PO else {}
    pr_current = {}
    if dt == PI:
        pr_lines = tuple(v[2] for v in own.values() if v[2]) or ("",)
        pr_current = dict(frappe.db.sql(
            "SELECT name, IFNULL(project, '') FROM `tabPurchase Receipt Item` WHERE name IN %s",
            (pr_lines,)))

    final = {}
    for line, current in lines:
        key = (child_dt, line)
        if key in plan.lines:
            final[line] = plan.lines[key]["to"]
            continue
        final[line] = current
        if current or dt == PO or not inf.readable or inf.closed or line not in own:
            continue
        po_line, db_project, pr_line = own[line]
        source = _planned(plan, ITEM_TABLE[PO], po_line, db_project) or db_project
        if not source or (header and header != source and not plan.overwrite):
            continue
        if pr_line and _planned(plan, ITEM_TABLE[PR], pr_line, pr_current.get(pr_line)) not in ("", source):
            continue
        # A blank line on a document this run touches, whose own PO line
        # names a project, takes it — the rule the run applies to the lines it
        # was asked about. Production GRNs receive two POs at once; without
        # this, one tagged earlier leaves them "mixed" for no reason.
        plan.lines[key] = {"doctype": dt, "parent": name, "from": "", "to": source,
                           "pos": set(state["pos"]), "inherited": True}
        plan.projects.add(source)
        final[line] = source

    state["changed"] = sum(1 for k, v in plan.lines.items() if v["doctype"] == dt and v["parent"] == name)
    state["lines_total"] = len(lines)
    effective = {final[line] or header for line in final}
    whole = effective.pop() if len(effective) == 1 else None
    state["whole"] = whole or None
    state["left_blank"] = sum(1 for line in final if not (final[line] or header))

    state["header_to"] = header
    if whole and header != whole:
        if not header or plan.overwrite:
            state["header_to"] = whole
        else:
            plan.conflicts.append({"doctype": dt, "name": name, "has": header, "want": whole})

    header_moves = state["header_to"] != header
    if dt == PO or inf.docstatus != 1:
        state["ledger"] = "none"
    elif dt == PR:
        # A GRN's GL rows carry its header project only: when the whole GRN
        # is on one project they are brought to it (a no-op if already
        # there); otherwise only its stock rows move, line by line.
        if whole and state["header_to"] == whole:
            state["ledger"] = "all"
        else:
            state["ledger"] = "stock" if state["changed"] else "none"
    elif not state["changed"] and not header_moves:
        state["ledger"] = "none"
    elif whole and state["header_to"] == whole:
        state["ledger"] = "all"
    else:
        state["ledger"] = "match"


def _doc_whole_project(plan, dt, name):
    """The single project a PO / invoice belongs to after this run, or None."""
    state = plan.docs.get((dt, name))
    if state is not None and "whole" in state:
        return state["whole"] if state.get("header_to") == state.get("whole") else None
    header = frappe.db.get_value(dt, name, "project") or ""
    lines = {(r[0] or header) for r in frappe.db.sql(
        "SELECT project FROM `tab{0}` WHERE parent=%s AND parenttype=%s".format(ITEM_TABLE[dt]),
        (name, dt))}
    return header if header and lines == {header} else None


def _plan_payments(plan):
    refs = tuple({n for (dt, n) in plan.docs if dt == PI} | set(plan.targets)) or ("",)
    pe_names = frappe.db.sql_list(
        """SELECT DISTINCT per.parent FROM `tabPayment Entry Reference` per
           JOIN `tabPayment Entry` pe ON pe.name = per.parent
           WHERE pe.docstatus < 2 AND per.reference_doctype IN ('Purchase Invoice', 'Purchase Order')
             AND per.reference_name IN %(r)s""", {"r": refs})
    for pe in pe_names:
        d = frappe.db.get_value(PE, pe, ["company", "docstatus", "project", "party",
                                         "paid_amount", "custom_source_voucher_doctype",
                                         "custom_source_voucher"], as_dict=True)
        current = d.project or ""
        owners, pos, foreign = set(), set(), False
        for ref_dt, ref_name in frappe.db.sql(
                """SELECT reference_doctype, reference_name FROM `tabPayment Entry Reference`
                   WHERE parent=%s""", pe):
            if ref_dt not in (PI, PO):
                owners.add(None)
                continue
            if plan.info(ref_dt, ref_name).company != d.company:
                foreign = True
            owners.add(_doc_whole_project(plan, ref_dt, ref_name))
            pos |= plan.docs.get((ref_dt, ref_name), {}).get("pos", set()) or \
                ({ref_name} if ref_dt == PO else set())
        if foreign:
            plan.skip(PE, pe, _("Pays a document of another company — left as it is"))
            continue
        if len(owners) != 1 or None in owners:
            if not current:
                plan.skip(PE, pe, _("Also settles documents of another (or no) project — a payment "
                                    "carries one project, so it is left as it is"))
            continue
        target = owners.pop()
        if current == target:
            continue
        if current and not plan.overwrite:
            plan.conflicts.append({"doctype": PE, "name": pe, "has": current, "want": target})
            continue
        inf = plan.info(PE, pe)
        if inf.closed or not inf.readable:
            plan.skip(PE, pe, inf.closed or _("No access"))
            continue
        if current:
            plan.projects.add(current)
        plan.payments.append({"name": pe, "from": current, "to": target, "docstatus": d.docstatus,
                              "date": inf.date, "party": d.party, "pos": pos,
                              "paid_amount": flt(d.paid_amount),
                              "voucher": d.custom_source_voucher
                              if d.custom_source_voucher_doctype == "Payment Voucher" else None})


def _plan_journal_rows(plan):
    owned = {}
    for (dt, n) in plan.docs:
        if dt == PI:
            p = _doc_whole_project(plan, PI, n)
            if p:
                owned[n] = p
    if not owned:
        return
    rows = frappe.db.sql(
        """SELECT jea.name, jea.parent, IFNULL(jea.project, '') AS project, jea.account,
                  IFNULL(jea.party_type, '') AS party_type, IFNULL(jea.party, '') AS party,
                  jea.debit, jea.credit, jea.reference_type, jea.reference_name,
                  je.docstatus, je.company
           FROM `tabJournal Entry Account` jea
           JOIN `tabJournal Entry` je ON je.name = jea.parent
           WHERE je.docstatus < 2 AND jea.reference_type = 'Purchase Invoice'
             AND jea.reference_name IN %(r)s""", {"r": tuple(owned)}, as_dict=True)
    for r in rows:
        target = owned[r.reference_name]
        if r.project == target:
            continue
        if r.company != plan.info(PI, r.reference_name).company:
            plan.skip(JE, r.parent, _("Pays an invoice of another company — left as it is"))
            continue
        if r.project and not plan.overwrite:
            plan.conflicts.append({"doctype": JE, "name": r.parent, "has": r.project, "want": target})
            continue
        inf = plan.info(JE, r.parent)
        if inf.closed or not inf.readable:
            plan.skip(JE, r.parent, inf.closed or _("No access"))
            continue
        gl = None
        if r.docstatus == 1:
            hits = frappe.db.sql_list(
                """SELECT name FROM `tabGL Entry`
                   WHERE voucher_type='Journal Entry' AND voucher_no=%s AND is_cancelled=0
                     AND account=%s AND IFNULL(party, '')=%s
                     AND against_voucher_type='Purchase Invoice' AND against_voucher=%s
                     AND ABS(debit - %s) < 0.005 AND ABS(credit - %s) < 0.005""",
                (r.parent, r.account, r.party, r.reference_name, flt(r.debit), flt(r.credit)))
            if len(hits) != 1:
                # Linked after posting (reconciliation) or split since: the GL
                # row cannot be told apart, so neither side is touched.
                plan.skip(JE, r.parent, _("Its ledger row paying {0} cannot be identified — left as "
                                          "it is").format(r.reference_name))
                continue
            gl = hits[0]
        if r.project:
            plan.projects.add(r.project)
        plan.journal_rows.append({"name": r.name, "parent": r.parent, "from": r.project,
                                  "to": target, "docstatus": r.docstatus, "row": r, "gl": gl,
                                  "pos": plan.docs.get((PI, r.reference_name), {}).get("pos", set())})


def _closed_reason(company, posting_date, dt):
    """Why the ledger of a voucher dated ``posting_date`` must not be touched,
    or None. Same three locks ERPNext itself honours when posting."""
    if not posting_date:
        return None
    date = getdate(posting_date)
    if frappe.db.has_column("Company", "accounts_frozen_till_date"):
        frozen = frappe.get_cached_value("Company", company, "accounts_frozen_till_date")
        if frozen and date <= getdate(frozen):
            return _("Accounts are frozen up to {0}").format(frappe.format_value(frozen, {"fieldtype": "Date"}))
    pcv = frappe.db.sql(
        """SELECT MAX(period_end_date) FROM `tabPeriod Closing Voucher`
           WHERE company=%s AND docstatus=1""", company)[0][0]
    if pcv and date <= getdate(pcv):
        return _("The books are closed up to {0}").format(frappe.format_value(pcv, {"fieldtype": "Date"}))
    ap = frappe.db.sql(
        """SELECT ap.name FROM `tabAccounting Period` ap
           JOIN `tabClosed Document` cd ON cd.parent = ap.name
           WHERE ap.company=%s AND IFNULL(ap.disabled, 0)=0 AND %s BETWEEN ap.start_date AND ap.end_date
             AND cd.document_type=%s AND cd.closed=1 LIMIT 1""", (company, date, dt))
    if ap:
        return _("Accounting Period {0} is closed for {1}").format(ap[0][0], dt)
    return None


def match_ledger(existing, expected, round_off_account=None, header_project=""):
    """Pair posted GL rows with the rows ERPNext would post now, ignoring the
    project, and return ``{gl_name: project}`` — or None when the two sets are
    not the same rows (a merge that would now split, a changed rate, …).

    Within rows that look alike, a row keeps its own project when that
    project is still wanted, so equal rows never trade places. ``existing``:
    dicts with name, account, party_type, party, cost_center, debit, credit,
    project. ``expected``: the same keys. Pure."""
    def key(r):
        return (r.get("account"), r.get("party_type") or "", r.get("party") or "",
                r.get("cost_center") or "", round(flt(r.get("debit")), 2),
                round(flt(r.get("credit")), 2))

    pool = defaultdict(list)
    for r in expected:
        if flt(r.get("debit")) or flt(r.get("credit")):
            pool[key(r)].append(r.get("project") or "")
    out, pending = {}, []
    for r in existing:
        k, current = key(r), r.get("project") or ""
        if current in pool.get(k, []):
            pool[k].remove(current)
            out[r["name"]] = current
        else:
            pending.append(r)
    for r in pending:
        k = key(r)
        if pool.get(k):
            out[r["name"]] = pool[k].pop()
        elif round_off_account and r.get("account") == round_off_account:
            out[r["name"]] = header_project or ""
        else:
            return None
    if any(pool.values()):
        return None
    return out


def _mixed_pairs(plan, dt, name, state):
    """For a MIXED invoice: the project each posted GL row should carry, as
    ``{gl_name: project}``, or None when the rows cannot be paired.

    Works on an in-memory copy with the planned projects applied — nothing is
    saved — so the preview can say up front which documents will need a
    repost, and Apply writes exactly what the preview showed. Re-derived the
    way ERPNext posts an invoice: ``get_gl_entries`` merges internally and the
    rows are then processed WITHOUT a second merge."""
    from erpnext.accounts.general_ledger import process_gl_map

    log = frappe.local.message_log if isinstance(frappe.local.message_log, list) else []
    messages = len(log)
    doc = frappe.get_doc(dt, name)
    for it in doc.get("items"):
        change = plan.lines.get((ITEM_TABLE[dt], it.name))
        if change:
            it.project = change["to"]
    doc.project = state["header_to"]
    sp = "dux_project_regen"
    frappe.db.savepoint(sp)
    try:
        expected = process_gl_map(doc.get_gl_entries(), merge_entries=False)
    except _REDERIVE_ERRORS:
        expected = None
    finally:
        # get_gl_entries is meant to be read-only; make sure of it. A failed
        # rollback (savepoint gone after a deadlock) propagates and aborts.
        frappe.db.rollback(save_point=sp)
        # A throw inside the dry run must not pop up on a run that succeeded.
        del log[messages:]
    if expected is None:
        return None
    existing = frappe.db.sql(
        """SELECT name, account, IFNULL(party_type, '') AS party_type, IFNULL(party, '') AS party,
                  IFNULL(cost_center, '') AS cost_center, debit, credit, IFNULL(project, '') AS project
           FROM `tabGL Entry` WHERE voucher_type=%s AND voucher_no=%s AND is_cancelled=0""",
        (dt, name), as_dict=True)
    round_off = frappe.get_cached_value("Company", doc.company, "round_off_account")
    return match_ledger(existing, expected, round_off, state["header_to"])


# =====================================================================
# Execution
# =====================================================================

def _execute(plan):
    user = frappe.session.user
    notes = defaultdict(list)       # (dt, name) -> sentences for the timeline comment
    origins = defaultdict(set)      # (dt, name) -> POs that reached it

    for (child_dt, child), c in plan.lines.items():
        frappe.db.set_value(child_dt, child, "project", c["to"], update_modified=False)

    for (dt, name), state in plan.docs.items():
        if not state["changed"] and state["header_to"] == state["header_from"]:
            continue
        if state["header_to"] != state["header_from"]:
            frappe.db.set_value(dt, name, "project", state["header_to"])
        ledger = state.get("ledger")
        if ledger == "all":
            state["ledger_rows"] = _tag_whole_voucher(dt, name, state["header_to"])
        elif ledger == "stock":
            _tag_stock_lines(plan, dt, name, state["header_to"])
        elif ledger in ("match", "unmatched"):
            _tag_stock_lines(plan, dt, name, state["header_to"])
            state["ledger_rows"] = _write_pairs(dt, name, state.get("pairs"))
        notes[(dt, name)].append(_line_note(state))
        origins[(dt, name)] |= state["pos"]

    for p in plan.payments:
        frappe.db.set_value(PE, p["name"], "project", p["to"])
        if p["docstatus"] == 1:
            p["ledger_rows"] = _tag_whole_voucher(PE, p["name"], p["to"])
        notes[(PE, p["name"])].append(_("Project set to {0} (was {1}); every document it pays "
                                        "belongs to that project.").format(
                                            _pname(p["to"]), _pname(p["from"])))
        origins[(PE, p["name"])] |= p["pos"]
        if p.get("voucher"):
            p["voucher_row"] = _sync_payment_voucher_row(p, plan.overwrite)

    for j in plan.journal_rows:
        frappe.db.set_value("Journal Entry Account", j["name"], "project", j["to"],
                            update_modified=False)
        if j["gl"]:
            frappe.db.set_value("GL Entry", j["gl"], "project", j["to"], update_modified=False)
            frappe.db.sql(
                """UPDATE `tabPayment Ledger Entry` SET project=%s
                   WHERE voucher_type='Journal Entry' AND voucher_no=%s AND delinked=0
                     AND against_voucher_type='Purchase Invoice' AND against_voucher_no=%s
                     AND account=%s""",
                (j["to"], j["parent"], j["row"].reference_name, j["row"].account))
            j["ledger_rows"] = 1
        notes[(JE, j["parent"])].append(_("Project set to {0} on the row paying {1}.").format(
            _pname(j["to"]), j["row"].reference_name))
        origins[(JE, j["parent"])] |= j["pos"]

    for (dt, name), sentences in notes.items():
        frappe.get_doc({
            "doctype": "Comment", "comment_type": "Info",
            "reference_doctype": dt, "reference_name": name,
            "content": frappe.utils.escape_html(_("{0} Set via Set Project on Purchase Order {1} by {2}.").format(
                " ".join(sentences), ", ".join(sorted(origins[(dt, name)])), user)),
        }).insert(ignore_permissions=True)


def _pname(project):
    if not project:
        return _("blank")
    return frappe.db.get_value("Project", project, "project_name") or project


def _line_note(state):
    parts = []
    if state["changed"]:
        parts.append(_("Project set on {0} line(s).").format(state["changed"]))
    if state["header_to"] != state["header_from"]:
        parts.append(_("Header project {0} → {1}.").format(_pname(state["header_from"]),
                                                         _pname(state["header_to"])))
    ledger = state.get("ledger")
    if ledger == "all":
        parts.append(_("Ledger rows retagged: {0}.").format(state.get("ledger_rows", 0)))
    elif ledger == "match":
        parts.append(_("Ledger rows retagged line by line: {0}.").format(state.get("ledger_rows", 0)))
    elif ledger == "unmatched":
        parts.append(_("Its ledger could not be matched line by line and was left unchanged."))
    return " ".join(parts)


def _tag_whole_voucher(dt, name, project):
    """Every live ledger row of the voucher → ``project``. Returns GL rows changed."""
    where = "voucher_type=%s AND voucher_no=%s AND is_cancelled=0 AND IFNULL(project, '') != %s"
    gl = frappe.db.sql(f"SELECT COUNT(*) FROM `tabGL Entry` WHERE {where}",
                       (dt, name, project))[0][0]
    frappe.db.sql(f"UPDATE `tabGL Entry` SET project=%s WHERE {where}", (project, dt, name, project))
    frappe.db.sql(
        """UPDATE `tabStock Ledger Entry` SET project=%s
           WHERE voucher_type=%s AND voucher_no=%s AND is_cancelled=0""", (project, dt, name))
    frappe.db.sql(
        """UPDATE `tabPayment Ledger Entry` SET project=%s
           WHERE voucher_type=%s AND voucher_no=%s AND delinked=0""", (project, dt, name))
    return int(gl)


def _tag_stock_lines(plan, dt, name, header):
    """Stock ledger rows point at their line: give each changed line's rows
    the project ERPNext would have posted — the line's, else the header's."""
    child_dt = ITEM_TABLE[dt]
    for (cdt, line), c in plan.lines.items():
        if cdt == child_dt and c["parent"] == name:
            frappe.db.sql(
                """UPDATE `tabStock Ledger Entry` SET project=%s
                   WHERE voucher_type=%s AND voucher_no=%s AND voucher_detail_no=%s AND is_cancelled=0""",
                (c["to"] or header or "", dt, name, line))


def _write_pairs(dt, name, pairs):
    """GL rows of a mixed invoice, as paired in the plan. Returns rows
    changed, or None when they were left alone."""
    if pairs is None:
        return None
    current = dict(frappe.db.sql(
        """SELECT name, IFNULL(project, '') FROM `tabGL Entry`
           WHERE voucher_type=%s AND voucher_no=%s AND is_cancelled=0""", (dt, name)))
    changed = 0
    for gl, project in pairs.items():
        if gl in current and current[gl] != project:
            frappe.db.set_value("GL Entry", gl, "project", project, update_modified=False)
            changed += 1
    return changed


def _sync_payment_voucher_row(p, overwrite):
    """A party-wise Payment Voucher posts one Payment Entry per row; keep that
    row's Project in step when the row can be identified without doubt."""
    rows = frappe.db.sql(
        """SELECT name, IFNULL(project, '') FROM `tabPV Party Row`
           WHERE parent=%s AND parenttype='Payment Voucher' AND party=%s AND ABS(amount - %s) < 0.005""",
        (p["voucher"], p["party"], p["paid_amount"]))
    if len(rows) != 1:
        return None
    name, current = rows[0]
    if current == p["to"] or (current and not overwrite):
        return None
    frappe.db.set_value("PV Party Row", name, "project", p["to"], update_modified=False)
    frappe.get_doc({
        "doctype": "Comment", "comment_type": "Info",
        "reference_doctype": "Payment Voucher", "reference_name": p["voucher"],
        "content": frappe.utils.escape_html(_("Project on the row paying {0} set to {1} (Payment Entry {2}).").format(
            p["party"], _pname(p["to"]), p["name"])),
    }).insert(ignore_permissions=True)
    return name


def _refresh_project_costing(plan):
    """Project.total_purchase_cost reads invoice lines; recompute it for every
    project this run moved money into or out of. Best effort — the dashboard
    reads the ledger, not this field."""
    from erpnext.projects.doctype.project.project import update_costing_and_billing
    for project in plan.projects:
        try:
            update_costing_and_billing(project)
        except Exception:
            frappe.log_error(title=f"Set Project: costing refresh failed for {project}")


# =====================================================================
# Report
# =====================================================================

def _report(plan):
    docs = []
    per_po = defaultdict(lambda: {"lines": 0, "receipts": set(), "invoices": set()})
    for (child_dt, _child), c in plan.lines.items():
        if c["doctype"] == PO:
            per_po[c["parent"]]["lines"] += 1
    for (dt, name), s in plan.docs.items():
        moved = s["changed"] or s.get("header_to") != s.get("header_from")
        if not moved:
            continue
        if dt in (PR, PI):
            for po in s["pos"]:
                per_po[po]["receipts" if dt == PR else "invoices"].add(name)
        docs.append({"doctype": dt, "kind": KIND[dt], "name": name, "pos": sorted(s["pos"]),
                     "lines": s["changed"], "lines_total": s.get("lines_total"),
                     "left_blank": s.get("left_blank", 0),
                     "header_from": s["header_from"], "header_to": s["header_to"],
                     "ledger": s.get("ledger"), "ledger_rows": s.get("ledger_rows"),
                     "date": s.get("date"), "draft": s.get("docstatus") == 0})
    for p in plan.payments:
        docs.append({"doctype": PE, "kind": KIND[PE], "name": p["name"], "pos": sorted(p["pos"]),
                     "lines": 0, "header_from": p["from"], "header_to": p["to"],
                     "ledger": "all" if p["docstatus"] == 1 else "none",
                     "ledger_rows": p.get("ledger_rows"), "date": p["date"],
                     "draft": p["docstatus"] == 0, "voucher": p.get("voucher"),
                     "voucher_row": p.get("voucher_row")})
    for j in plan.journal_rows:
        docs.append({"doctype": JE, "kind": KIND[JE], "name": j["parent"], "pos": sorted(j["pos"]),
                     "lines": 1, "header_from": j["from"], "header_to": j["to"],
                     "ledger": "row" if j["docstatus"] == 1 else "none",
                     "ledger_rows": j.get("ledger_rows"), "pays": j["row"].reference_name,
                     "draft": j["docstatus"] == 0})

    blocked_by_po = defaultdict(int)
    for b in plan.blocked:
        blocked_by_po[b["purchase_order"]] += 1
    orders = []
    for o in plan.orders:
        po = o["purchase_order"]
        pp = per_po.get(po, {"lines": 0, "receipts": set(), "invoices": set()})
        s = plan.docs.get((PO, po), {})
        status = o["status"]
        if status == "ready":
            changes = pp["lines"] or pp["receipts"] or pp["invoices"] or \
                s.get("header_to") != s.get("header_from")
            if blocked_by_po[po] and not changes:
                status = "blocked"
            elif blocked_by_po[po]:
                status = "partly"
            elif not changes:
                status = "already"
        orders.append({**{k: v for k, v in o.items() if k != "line"}, "status": status,
                       "sheet_line": o.get("line"), "lines": pp["lines"],
                       "receipts": sorted(pp["receipts"]), "invoices": sorted(pp["invoices"]),
                       "blocked_lines": blocked_by_po[po]})

    names = set(plan.projects) | {c["has"] for c in plan.conflicts} | {c["want"] for c in plan.conflicts}
    return {
        "orders": orders,
        "documents": sorted(docs, key=lambda d: (list(KIND).index(d["doctype"]), d["name"])),
        "blocked": plan.blocked,
        "skipped": plan.skipped,
        "conflicts": plan.conflicts,
        "warnings": plan.warnings,
        "project_names": {p: _pname(p) for p in names if p},
        "totals": {
            "orders": sum(1 for o in orders if o["status"] in ("ready", "partly")),
            "receipts": sum(1 for d in docs if d["doctype"] == PR),
            "invoices": sum(1 for d in docs if d["doctype"] == PI),
            "payments": sum(1 for d in docs if d["doctype"] == PE),
            "journals": sum(1 for d in docs if d["doctype"] == JE),
            "errors": sum(1 for o in orders if o["status"] == "error"),
            "unmatched": sum(1 for d in docs if d.get("ledger") == "unmatched"),
            "blocked_lines": len(plan.blocked),
        },
        "overwrite": plan.overwrite,
    }
