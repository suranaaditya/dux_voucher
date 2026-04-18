import csv
import io

import frappe
from frappe import _
from frappe.utils import flt
from frappe.utils.file_manager import get_file


@frappe.whitelist()
def import_from_csv(batch_name, file_url):
    """
    Parse a CSV/TSV file attached to an Ex Student Opening Batch and
    populate its students_table. Auto-creates Ex Student masters for
    any student_name not found in the batch's company.

    Expected columns (header row, case-insensitive, order-flexible):
        student_name (required), amount (required),
        father_name, course, batch_year, mobile, email, remarks

    Returns a summary dict so the JS can show it.
    """
    if not batch_name or not file_url:
        frappe.throw(_('batch_name and file_url are required'))

    batch = frappe.get_doc('Ex Student Opening Batch', batch_name)
    if batch.docstatus != 0:
        frappe.throw(_('Cannot import into a submitted batch'))
    if not batch.company:
        frappe.throw(_('Set Company on the batch before importing'))

    _, content = get_file(file_url)
    if isinstance(content, bytes):
        content = content.decode('utf-8-sig', errors='replace')

    rows = _parse_csv(content)
    if not rows:
        frappe.throw(_('CSV has no data rows'))

    created = 0
    appended = 0
    errors = []

    for idx, row in enumerate(rows, start=2):  # row 1 = header
        try:
            student_name = (row.get('student_name') or '').strip()
            amount = flt(row.get('amount'))
            if not student_name:
                errors.append(_('Row {0}: missing student_name').format(idx))
                continue
            if amount <= 0:
                errors.append(_('Row {0}: amount must be > 0').format(idx))
                continue

            ex_student_id = _get_or_create_ex_student(
                student_name=student_name,
                company=batch.company,
                father_name=row.get('father_name'),
                course=row.get('course'),
                batch_year=row.get('batch_year'),
                mobile=row.get('mobile'),
                email=row.get('email'),
            )
            if ex_student_id.get('created'):
                created += 1

            batch.append('students_table', {
                'ex_student': ex_student_id['name'],
                'amount': amount,
                'remarks': (row.get('remarks') or '').strip() or None,
            })
            appended += 1
        except Exception as e:
            errors.append(_('Row {0}: {1}').format(idx, str(e)))

    batch.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        'created': created,
        'appended': appended,
        'errors': errors,
    }


def _parse_csv(content):
    sample = content[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=',\t;|')
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(content), dialect=dialect)
    raw = [r for r in reader if any((c or '').strip() for c in r)]
    if not raw:
        return []

    header = [h.strip().lower() for h in raw[0]]
    rows = []
    for line in raw[1:]:
        record = {}
        for i, cell in enumerate(line):
            if i < len(header):
                record[header[i]] = cell
        rows.append(record)
    return rows


def _get_or_create_ex_student(student_name, company, **extra):
    existing = frappe.db.get_value(
        'Ex Student',
        {'student_name': student_name, 'company': company},
        'name',
    )
    if existing:
        return {'name': existing, 'created': False}

    doc = frappe.new_doc('Ex Student')
    doc.student_name = student_name
    doc.company = company
    for k, v in extra.items():
        if v:
            doc.set(k, v)
    doc.insert(ignore_permissions=True)
    return {'name': doc.name, 'created': True}


def _current_outstanding(ex_student):
    """Return current outstanding = SUM(debit) - SUM(credit) from non-cancelled ledger entries."""
    row = frappe.db.sql(
        '''
        SELECT SUM(debit) - SUM(credit)
        FROM `tabEx Student Ledger Entry`
        WHERE ex_student = %s AND is_cancelled = 0
        ''',
        (ex_student,),
    )
    return flt(row[0][0]) if row and row[0][0] is not None else 0


@frappe.whitelist()
def get_outstanding(ex_student):
    """Whitelisted: return current outstanding balance for a student (positive = owes us)."""
    if not ex_student:
        return 0
    return _current_outstanding(ex_student)
