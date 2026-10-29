"""Does the GL agree with the ex-students?

An ex-student's balance lives in two places that nothing used to compare:
the ``Ex Student Ledger Entry`` rows (per student) and the GL account
``Ex-Students Receivable - {abbr}`` (one party-less total per company, fed
by each voucher's netted journal). A journal posted straight onto the
account moves the GL without moving any student; a ledger row changed by
hand moves a student without moving the GL.

This compares the two per company and EXPLAINS the gap item by item:

* ``outside``  — a posting on the account by anything that is not an Ex
  Student voucher (a manual JV, a voucher's head-wise line, a migration
  opening entry). Its whole amount is GL the students do not have.
* ``mismatch`` — an Ex Student voucher whose journal and ledger rows
  disagree (a row edited or revived by hand, a journal cancelled behind
  the voucher's back). The difference between the two.

The items always add up to the gap, so the report is a work list, not
just a number. ``daily_check`` runs it every night and tells the Accounts
Managers (in-app) when the gaps change.
"""

import json
from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt, fmt_money

from dux_voucher.dux_voucher.doctype.ex_student_ledger_entry.ex_student_ledger_entry import (
    POSTING_VOUCHERS,
)

_STATE = ('__dux_ex_student_recon', 'last_gaps')   # (DefaultValue parent, key)


def _explain(outside, gl_by_voucher, students_by_voucher):
    """Items that make up GL − students (pure).

    ``outside``             [{voucher_type, voucher_no, posting_date, amount}]
    ``gl_by_voucher``       {(voucher_type, voucher_no): journal net on the account}
    ``students_by_voucher`` {(voucher_type, voucher_no): live ledger-row net}
    """
    items = [dict(kind='outside', voucher_type=o['voucher_type'], voucher_no=o['voucher_no'],
                  posting_date=o.get('posting_date'), gl=flt(o['amount'], 2), students=0.0,
                  amount=flt(o['amount'], 2))
             for o in outside if abs(flt(o['amount'])) >= 0.005]
    for key in sorted(set(gl_by_voucher) | set(students_by_voucher)):
        gl, st = flt(gl_by_voucher.get(key), 2), flt(students_by_voucher.get(key), 2)
        if abs(gl - st) >= 0.005:
            items.append(dict(kind='mismatch', voucher_type=key[0], voucher_no=key[1],
                              posting_date=None, gl=gl, students=st, amount=flt(gl - st, 2)))
    return items


def _companies(company=None):
    """``{company: receivable account}`` for every company with ex-students
    or the account."""
    if company:
        names = [company]
    else:
        names = set(frappe.db.sql_list('SELECT DISTINCT company FROM `tabEx Student`'))
        names |= set(frappe.db.sql_list(
            "SELECT company FROM `tabAccount` WHERE account_name = 'Ex-Students Receivable'"))
    out = {}
    for co in sorted(n for n in names if n):
        abbr = frappe.get_cached_value('Company', co, 'abbr')
        if abbr:
            out[co] = f'Ex-Students Receivable - {abbr}'
    return out


def reconcile_company(company, account):
    """GL vs students for one company, with the items that explain the gap.
    Queried per company (the account index does the work)."""
    has_account = frappe.db.exists('Account', account)
    outside, gl_by_voucher, gl = [], defaultdict(float), 0.0
    if has_account:
        for r in frappe.db.sql(
            '''
            SELECT g.voucher_type, g.voucher_no, MIN(g.posting_date) AS posting_date,
                   SUM(g.debit - g.credit) AS amount,
                   je.custom_source_voucher_doctype AS src_dt, je.custom_source_voucher AS src
            FROM `tabGL Entry` g
            LEFT JOIN `tabJournal Entry` je
                   ON g.voucher_type = 'Journal Entry' AND je.name = g.voucher_no
            WHERE g.account = %s AND g.is_cancelled = 0
            GROUP BY g.voucher_type, g.voucher_no,
                     je.custom_source_voucher_doctype, je.custom_source_voucher
            ''', (account,), as_dict=True):
            gl += flt(r.amount)
            if r.src_dt in POSTING_VOUCHERS and r.src:
                gl_by_voucher[(r.src_dt, r.src)] += flt(r.amount)
            else:
                outside.append(r)
    students_by_voucher = {(vt, vn): flt(net) for vt, vn, net in frappe.db.sql(
        '''
        SELECT voucher_type, voucher_no, SUM(debit - credit)
        FROM `tabEx Student Ledger Entry`
        WHERE company = %s AND is_cancelled = 0
        GROUP BY voucher_type, voucher_no
        ''', (company,))}
    students = sum(students_by_voucher.values())
    items = _explain(outside, gl_by_voucher, students_by_voucher)
    difference = flt(gl - students, 2)
    unexplained = flt(difference - sum(i['amount'] for i in items), 2)
    if abs(unexplained) >= 0.005:   # cannot happen by construction; never hide it if it does
        items.append(dict(kind='unexplained', voucher_type='', voucher_no='', posting_date=None,
                          gl=0.0, students=0.0, amount=unexplained))
    return dict(company=company, account=account if has_account else None,
                gl=flt(gl, 2), students=flt(students, 2), difference=difference, items=items)


def permitted_companies(user=None):
    """Companies ``user`` may see — as Frappe itself resolves their Company
    User Permissions (a trust's permission covers its institutes unless
    descendants are hidden), counting those that apply to every doctype or
    to Ex Student. ``None``: no restriction."""
    from frappe.permissions import get_user_permissions
    perms = get_user_permissions(user or frappe.session.user).get('Company') or []
    allowed = {p.get('doc') for p in perms
               if not p.get('applicable_for') or p.get('applicable_for') == 'Ex Student'}
    return allowed or None


def reconcile(company=None, user=None):
    """Per company the user may see — figures of an institution they are
    not allowed are never returned."""
    allowed = permitted_companies(user)
    if company and allowed is not None and company not in allowed:
        frappe.throw(_('You do not have access to {0}.').format(company), frappe.PermissionError)
    return [reconcile_company(co, acc) for co, acc in _companies(company).items()
            if allowed is None or co in allowed]


# ──────────────────────────────────────────────────────────────────────
# Nightly check
# ──────────────────────────────────────────────────────────────────────

def daily_check():
    """Scheduled daily. Tells the Accounts Managers in-app (bell, never
    email) when the set of companies out of step, or their gaps, change —
    not every night the same gap stands."""
    every = [reconcile_company(co, acc) for co, acc in _companies().items()]
    gaps = {r['company']: r['difference'] for r in every if abs(r['difference']) >= 0.01}
    parent, key = _STATE
    previous = json.loads(frappe.db.get_default(key, parent=parent) or '{}')
    frappe.db.set_default(key, json.dumps(gaps, sort_keys=True), parent=parent)
    if not gaps or gaps == previous:
        return
    users = frappe.db.sql_list(
        '''
        SELECT DISTINCT u.name FROM `tabUser` u
        JOIN `tabHas Role` r ON r.parent = u.name AND r.parenttype = 'User'
        WHERE r.role = 'Accounts Manager' AND u.enabled = 1
          AND u.name NOT IN ('Administrator', 'Guest') AND u.user_type = 'System User'
        ''')
    for user in users:
        allowed = permitted_companies(user)
        mine = {co: v for co, v in gaps.items() if allowed is None or co in allowed}
        if not mine:
            continue    # nothing out of step that this manager may see
        total = sum(abs(v) for v in mine.values())
        subject = _('Ex Students: the GL and the student ledger differ in {0} compan{1} ({2})').format(
            len(mine), 'y' if len(mine) == 1 else 'ies', fmt_money(total, currency='INR'))
        body = '<br>'.join(f'{frappe.utils.escape_html(co)}: {fmt_money(v, currency="INR")}'
                           for co, v in sorted(mine.items()))
        body += '<br><br>' + _('Open the Ex Student Reconciliation report to see the entries behind each gap.')
        frappe.get_doc({
            'doctype': 'Notification Log',
            'for_user': user,
            'type': 'Alert',
            'subject': subject,
            'email_content': body,
            'link': '/app/query-report/Ex Student Reconciliation',
        }).insert(ignore_permissions=True)
