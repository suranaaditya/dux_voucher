"""Ex Student Reconciliation — per company, the GL account Ex-Students
Receivable against the sum of the students' ledgers, and the entries that
explain any gap (api/ex_student_recon.py)."""

import frappe
from frappe import _
from frappe.utils import flt

from dux_voucher.dux_voucher.api.ex_student_recon import reconcile


def _note(kind):
    return {
        'outside': _('Posted to Ex-Students Receivable outside the Ex Student module: '
                     'no student carries it'),
        'mismatch': _('Ex Student voucher whose journal and student rows disagree'),
        'unexplained': _('Not explained by any single entry'),
    }.get(kind, '')


def execute(filters=None):
    filters = frappe._dict(filters or {})
    results = reconcile(filters.get('company'))
    data = []
    for r in results:
        gap = abs(r['difference']) >= 0.005
        if filters.get('only_differences') and not gap:
            continue
        data.append(dict(
            name=r['company'], parent='', indent=0,
            label=r['company'],
            gl=r['gl'], students=r['students'], difference=r['difference'],
            note=(_('No Ex-Students Receivable account') if not r['account']
                  else _('Agrees') if not gap else _('{0} entr{1} explain the gap').format(
                      len(r['items']), 'y' if len(r['items']) == 1 else 'ies')),
        ))
        for i, item in enumerate(r['items']):
            data.append(dict(
                name=f"{r['company']}::{i}", parent=r['company'], indent=1,
                label=item['voucher_type'] or _('(unexplained)'),
                voucher_type=item['voucher_type'], voucher_no=item['voucher_no'],
                posting_date=item.get('posting_date'),
                gl=item['gl'], students=item['students'], difference=item['amount'],
                note=_note(item['kind']),
            ))

    out_of_step = [r for r in results if abs(r['difference']) >= 0.005]
    summary = [
        dict(value=len(results), label=_('Companies checked'), datatype='Int', indicator='Blue'),
        dict(value=len(out_of_step), label=_('Companies with a gap'), datatype='Int',
             indicator='Red' if out_of_step else 'Green'),
        dict(value=flt(sum(abs(r['difference']) for r in out_of_step), 2), label=_('Total gap'),
             datatype='Currency', indicator='Red' if out_of_step else 'Green'),
    ]
    return _columns(), data, None, None, summary


def _columns():
    return [
        {'label': _('Company / Entry'), 'fieldname': 'label', 'fieldtype': 'Data', 'width': 300},
        {'label': _('Voucher'), 'fieldname': 'voucher_no', 'fieldtype': 'Dynamic Link',
         'options': 'voucher_type', 'width': 220},
        {'label': _('Date'), 'fieldname': 'posting_date', 'fieldtype': 'Date', 'width': 100},
        {'label': _('As per GL'), 'fieldname': 'gl', 'fieldtype': 'Currency', 'width': 150},
        {'label': _('As per Students'), 'fieldname': 'students', 'fieldtype': 'Currency', 'width': 150},
        {'label': _('Difference'), 'fieldname': 'difference', 'fieldtype': 'Currency', 'width': 140},
        {'label': _('Note'), 'fieldname': 'note', 'fieldtype': 'Data', 'width': 420},
        {'label': _('Voucher Type'), 'fieldname': 'voucher_type', 'fieldtype': 'Link',
         'options': 'DocType', 'hidden': 1},
    ]
