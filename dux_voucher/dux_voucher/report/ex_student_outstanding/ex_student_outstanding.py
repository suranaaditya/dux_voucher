import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
    filters = filters or {}
    columns = _columns()
    data = _data(filters)
    return columns, data


def _columns():
    return [
        {'label': _('Ex Student'), 'fieldname': 'ex_student', 'fieldtype': 'Link', 'options': 'Ex Student', 'width': 130},
        {'label': _('Student Name'), 'fieldname': 'student_name', 'fieldtype': 'Data', 'width': 220},
        {'label': _('Company'), 'fieldname': 'company', 'fieldtype': 'Link', 'options': 'Company', 'width': 220},
        {'label': _('Course'), 'fieldname': 'course', 'fieldtype': 'Data', 'width': 120},
        {'label': _('Batch'), 'fieldname': 'batch_year', 'fieldtype': 'Data', 'width': 80},
        {'label': _('Opening'), 'fieldname': 'opening', 'fieldtype': 'Currency', 'width': 120},
        {'label': _('Received'), 'fieldname': 'received', 'fieldtype': 'Currency', 'width': 120},
        {'label': _('Written Off'), 'fieldname': 'written_off', 'fieldtype': 'Currency', 'width': 120},
        {'label': _('Outstanding'), 'fieldname': 'outstanding', 'fieldtype': 'Currency', 'width': 130, 'bold': 1},
    ]


def _data(filters):
    conds = ['es.is_disabled = 0']
    params = {}

    if filters.get('company'):
        conds.append('es.company = %(company)s')
        params['company'] = filters['company']

    if filters.get('ex_student'):
        conds.append('es.name = %(ex_student)s')
        params['ex_student'] = filters['ex_student']

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
            es.company,
            es.course,
            es.batch_year,
            COALESCE(SUM(CASE WHEN le.voucher_type = 'Ex Student Opening Batch'
                              AND le.is_cancelled = 0 {date_clause}
                              THEN le.debit ELSE 0 END), 0) AS opening,
            COALESCE(SUM(CASE WHEN le.voucher_type = 'Ex Student Receipt'
                              AND le.is_cancelled = 0 {date_clause}
                              THEN le.credit ELSE 0 END), 0) AS received,
            COALESCE(SUM(CASE WHEN le.voucher_type = 'Ex Student Writeoff'
                              AND le.is_cancelled = 0 {date_clause}
                              THEN le.credit ELSE 0 END), 0) AS written_off,
            COALESCE(SUM(CASE WHEN le.is_cancelled = 0 {date_clause}
                              THEN le.debit - le.credit ELSE 0 END), 0) AS outstanding
        FROM `tabEx Student` es
        LEFT JOIN `tabEx Student Ledger Entry` le ON le.ex_student = es.name
        WHERE {where_students}
        GROUP BY es.name
        HAVING outstanding != 0 OR %(show_zero)s = 1
        ORDER BY es.company, es.student_name
        ''',
        {**params, 'show_zero': 1 if filters.get('show_zero') else 0},
        as_dict=True,
    )

    for r in rows:
        for k in ('opening', 'received', 'written_off', 'outstanding'):
            r[k] = flt(r[k])
    return rows
