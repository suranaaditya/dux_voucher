import frappe
from frappe import _
from frappe.utils import flt, fmt_money


def execute(filters=None):
    filters = filters or {}
    columns = _columns()
    data = _data(filters)
    return columns, data, _gl_gap_message(filters)


def _gl_gap_message(filters):
    """Say plainly what this report's total does NOT tie to: a gap between
    Ex-Students Receivable and the students' ledgers (posted around the
    module — no student carries it), and balances held by disabled
    students, which the rows leave out. Both as of today."""
    from dux_voucher.dux_voucher.api.ex_student_recon import permitted_companies, reconcile
    company = filters.get('company')
    allowed = permitted_companies()
    if company and allowed is not None and company not in allowed:
        return None     # the banner never breaks the report
    parts = []
    gaps = [r for r in reconcile(company) if abs(r['difference']) >= 0.005]
    if gaps:
        lines = ''.join(
            '<li>{0}: {1}</li>'.format(frappe.utils.escape_html(r['company']),
                                       fmt_money(r['difference'], currency='INR'))
            for r in gaps[:10])
        more = _('<li>and {0} more</li>').format(len(gaps) - 10) if len(gaps) > 10 else ''
        parts.append(_(
            '<b>The GL does not agree with the students.</b> Ex-Students Receivable differs '
            'from the students\' ledgers in:<ul>{0}{1}</ul>See the Ex Student Reconciliation '
            'report for the entries behind each gap.'
        ).format(lines, more))
    disabled = frappe.db.sql(
        f'''
        SELECT COALESCE(SUM(le.debit - le.credit), 0)
        FROM `tabEx Student Ledger Entry` le
        JOIN `tabEx Student` es ON es.name = le.ex_student
        WHERE es.is_disabled = 1 AND le.is_cancelled = 0
          {'AND le.company = %(company)s' if company else ''}
          {'AND le.company IN %(allowed)s' if not company and allowed is not None else ''}
        ''', {'company': company, 'allowed': tuple(allowed or ('',))})[0][0]
    if abs(flt(disabled)) >= 0.005:
        parts.append(_(
            'Disabled students hold {0}, which is in the GL but not in these rows.'
        ).format(fmt_money(flt(disabled), currency='INR')))
    if parts and filters.get('as_of_date'):
        parts.append(_('These checks are as of today, not the As of Date.'))
    return '<br>'.join(parts) or None


def _columns():
    return [
        {'label': _('Ex Student'), 'fieldname': 'ex_student', 'fieldtype': 'Link', 'options': 'Ex Student', 'width': 130},
        {'label': _('Student Name'), 'fieldname': 'student_name', 'fieldtype': 'Data', 'width': 200},
        {'label': _('Student ID'), 'fieldname': 'student_id', 'fieldtype': 'Data', 'width': 100},
        {'label': _('Company'), 'fieldname': 'company', 'fieldtype': 'Link', 'options': 'Company', 'width': 200},
        {'label': _('Course'), 'fieldname': 'course', 'fieldtype': 'Data', 'width': 110},
        {'label': _('Batch'), 'fieldname': 'batch_year', 'fieldtype': 'Data', 'width': 80},
        {'label': _('Opening (Dr)'), 'fieldname': 'opening_dr', 'fieldtype': 'Currency', 'width': 115},
        {'label': _('Opening (Cr)'), 'fieldname': 'opening_cr', 'fieldtype': 'Currency', 'width': 115},
        {'label': _('Received'), 'fieldname': 'received', 'fieldtype': 'Currency', 'width': 110},
        {'label': _('Refunded'), 'fieldname': 'refunded', 'fieldtype': 'Currency', 'width': 110},
        {'label': _('Written Off'), 'fieldname': 'written_off', 'fieldtype': 'Currency', 'width': 110},
        {'label': _('Outstanding'), 'fieldname': 'outstanding', 'fieldtype': 'Currency', 'width': 120, 'bold': 1},
        {'label': _('Type'), 'fieldname': 'balance_type', 'fieldtype': 'Data', 'width': 70},
    ]


def _data(filters):
    conds = ['es.is_disabled = 0']
    params = {}
    if filters.get('company'):
        conds.append('es.company = %(company)s'); params['company'] = filters['company']
    if filters.get('ex_student'):
        conds.append('es.name = %(ex_student)s'); params['ex_student'] = filters['ex_student']

    date_clause = ''
    if filters.get('as_of_date'):
        date_clause = 'AND le.posting_date <= %(as_of_date)s'
        params['as_of_date'] = filters['as_of_date']

    where_students = ' AND '.join(conds)

    rows = frappe.db.sql(
        f'''
        SELECT
            es.name AS ex_student,
            es.student_name,
            es.student_id,
            es.company,
            es.course,
            es.batch_year,
            COALESCE(SUM(CASE WHEN le.voucher_type IN ('Ex Student Opening Batch', 'Ex Student Opening Adjustment')
                              AND le.is_cancelled = 0 {date_clause}
                              THEN le.debit - le.credit ELSE 0 END), 0) AS opening_net,
            COALESCE(SUM(CASE WHEN le.voucher_type = 'Ex Student Receipt'
                              AND le.is_cancelled = 0 {date_clause}
                              THEN le.credit ELSE 0 END), 0) AS received,
            COALESCE(SUM(CASE WHEN le.voucher_type = 'Ex Student Refund'
                              AND le.is_cancelled = 0 {date_clause}
                              THEN le.debit ELSE 0 END), 0) AS refunded,
            COALESCE(SUM(CASE WHEN le.voucher_type = 'Ex Student Writeoff'
                              AND le.is_cancelled = 0 {date_clause}
                              THEN le.credit ELSE 0 END), 0) AS written_off,
            COALESCE(SUM(CASE WHEN le.is_cancelled = 0 {date_clause}
                              THEN le.debit - le.credit ELSE 0 END), 0) AS outstanding
        FROM `tabEx Student` es
        LEFT JOIN `tabEx Student Ledger Entry` le ON le.ex_student = es.name
        WHERE {where_students}
        GROUP BY es.name
        HAVING outstanding != 0 OR opening_net != 0 OR %(show_zero)s = 1
        ORDER BY es.company, es.student_name
        ''',
        {**params, 'show_zero': 1 if filters.get('show_zero') else 0},
        as_dict=True,
    )

    for r in rows:
        # The opening is the batch plus any Opening Adjustments, netted onto
        # its own side: a corrected student shows one opening figure.
        net = flt(r.pop('opening_net'), 2)
        r['opening_dr'], r['opening_cr'] = (net, 0.0) if net > 0 else (0.0, -net)
        for k in ('received', 'refunded', 'written_off', 'outstanding'):
            r[k] = flt(r[k])
        # Compute balance_type from the signed outstanding
        if r['outstanding'] > 0.005:
            r['balance_type'] = 'Dr'
        elif r['outstanding'] < -0.005:
            r['balance_type'] = 'Cr'
            r['outstanding'] = abs(r['outstanding'])  # display as positive with Cr indicator
        else:
            r['balance_type'] = 'Nil'
    return rows
