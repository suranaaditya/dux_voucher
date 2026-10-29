import csv
import io
import json
import re

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, get_datetime, now_datetime, today
from frappe.utils.file_manager import get_file

# Ledger rows that make up a student's OPENING (as against receipts,
# refunds and write-offs, which move the balance after it).
OPENING_VOUCHER_TYPES = ('Ex Student Opening Batch', 'Ex Student Opening Adjustment')


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
            debit = flt(row.get('debit') or row.get('debit_amount'))
            credit = flt(row.get('credit') or row.get('credit_amount'))

            # Backward compat: if legacy 'amount' column provided with no debit/credit,
            # treat it as debit (owes us).
            if debit == 0 and credit == 0 and row.get('amount'):
                debit = flt(row.get('amount'))

            if not student_name:
                errors.append(_('Row {0}: missing student_name').format(idx))
                continue
            if debit <= 0 and credit <= 0:
                errors.append(_('Row {0}: provide debit or credit > 0').format(idx))
                continue
            if debit > 0 and credit > 0:
                errors.append(_('Row {0}: cannot have both debit and credit').format(idx))
                continue

            ex_student_id = _get_or_create_ex_student(
                student_name=student_name,
                company=batch.company,
                father_name=row.get('father_name'),
                course=row.get('course'),
                batch_year=row.get('batch_year'),
                admission_session=row.get('admission_session'),
                student_id=row.get('student_id'),
                mobile=row.get('mobile'),
                email=row.get('email'),
            )
            if ex_student_id.get('created'):
                created += 1

            batch.append('students_table', {
                'ex_student': ex_student_id['name'],
                'debit_amount': debit,
                'credit_amount': credit,
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
    """Return outstanding for a student as {'amount': signed_value, 'abs': abs_value, 'type': 'Dr|Cr|Nil'}.

    Positive = student owes (Dr). Negative = advance/credit balance (Cr).
    """
    if not ex_student:
        return {'amount': 0, 'abs': 0, 'type': 'Nil'}
    signed = _current_outstanding(ex_student)
    if signed > 0.005:
        return {'amount': signed, 'abs': signed, 'type': 'Dr'}
    elif signed < -0.005:
        return {'amount': signed, 'abs': abs(signed), 'type': 'Cr'}
    return {'amount': 0, 'abs': 0, 'type': 'Nil'}


# ──────────────────────────────────────────────────────────────────────
# Opening adjustments — correct one student's opening without touching
# the rest of their Opening Batch (doctype Ex Student Opening Adjustment)
# ──────────────────────────────────────────────────────────────────────

def _signed(amount, dr_cr):
    """Dr → +amount, Cr → −amount (pure)."""
    amount = abs(flt(amount))
    return -amount if dr_cr == 'Cr' else amount


def _split_signed(value):
    """Signed balance → (amount, 'Dr' | 'Cr' | 'Nil') (pure)."""
    value = flt(value, 2)
    if value > 0.005:
        return value, 'Dr'
    if value < -0.005:
        return -value, 'Cr'
    return 0.0, 'Nil'


def _adjustment(current_signed, correct_amount, correct_type):
    """``(debit, credit)`` that turns the current opening into the correct
    one (pure). Debit raises what the student owes; credit lowers it."""
    diff = flt(_signed(correct_amount, correct_type) - flt(current_signed), 2)
    return (diff, 0.0) if diff > 0 else (0.0, -diff)


def _change_text(debit, credit):
    """'₹ 36,000.00 Cr' — the row's change as an accountant reads it."""
    if flt(debit):
        return '{0} Dr'.format(frappe.format_value(flt(debit), {'fieldtype': 'Currency'}))
    if flt(credit):
        return '{0} Cr'.format(frappe.format_value(flt(credit), {'fieldtype': 'Currency'}))
    return ''


def _current_openings(ex_students, company, locking=False):
    """``{ex_student: signed opening}`` in ``company`` from the live opening
    rows — every Opening Batch and Opening Adjustment row, nothing posted
    after them. Per company: a student moved to another company after
    posting keeps the old rows (and the old company's GL) behind.

    ``locking``: read the latest committed rows (a locking read) rather
    than the transaction's snapshot — for use after the students are
    locked on submit / cancel, where a plain read could still see the
    figures from before a concurrent posting committed."""
    ex_students = tuple({s for s in ex_students if s})
    if not ex_students:
        return {}
    return {s: flt(v) for s, v in frappe.db.sql(
        '''
        SELECT ex_student, SUM(debit - credit)
        FROM `tabEx Student Ledger Entry`
        WHERE ex_student IN %s AND company = %s AND is_cancelled = 0 AND voucher_type IN %s
        GROUP BY ex_student
        ''' + (' LOCK IN SHARE MODE' if locking else ''),
        (ex_students, company, OPENING_VOUCHER_TYPES),
    )}


@frappe.whitelist()
def get_opening_details(ex_students):
    """Each student's current opening (in the student's own company), for
    the adjustment grid and the Ex Student form: ``{name: {student_name,
    company, is_disabled, amount, type}}``."""
    frappe.has_permission('Ex Student', 'read', throw=True)
    if isinstance(ex_students, str):
        ex_students = json.loads(ex_students) if ex_students.startswith('[') else [ex_students]
    names = list({s for s in (ex_students or []) if s})[:5000]
    if not names:
        return {}
    # get_list, not get_all: a user limited to one institute sees only its students
    students = frappe.get_list('Ex Student', filters={'name': ('in', names)},
                               fields=['name', 'student_name', 'company', 'is_disabled'],
                               limit_page_length=0)
    openings = {}
    for company in {s.company for s in students}:
        openings.update(_current_openings([s.name for s in students if s.company == company], company))
    out = {}
    for s in students:
        amount, dr_cr = _split_signed(openings.get(s.name, 0))
        out[s.name] = dict(student_name=s.student_name, company=s.company,
                           is_disabled=s.is_disabled, amount=amount, type=dr_cr)
    return out


@frappe.whitelist()
def get_adjustment_defaults(company=None, ex_student=None, batch=None):
    """``{company, posting_date}`` for a new Opening Adjustment: the date of
    the opening being corrected — the batch's own date when started from a
    batch, the student's latest opening row when started from a student,
    else the company's first Opening Batch."""
    frappe.has_permission('Ex Student Opening Adjustment', 'create', throw=True)
    posting_date = None
    if batch:
        frappe.has_permission('Ex Student Opening Batch', 'read', doc=batch, throw=True)
        company, posting_date = frappe.db.get_value(
            'Ex Student Opening Batch', batch, ['company', 'posting_date']) or (company, None)
    elif ex_student:
        frappe.has_permission('Ex Student', 'read', doc=ex_student, throw=True)
        company = frappe.db.get_value('Ex Student', ex_student, 'company') or company
        posting_date = frappe.db.sql(
            '''SELECT MAX(posting_date) FROM `tabEx Student Ledger Entry`
               WHERE ex_student = %s AND company = %s AND is_cancelled = 0 AND voucher_type IN %s''',
            (ex_student, company, OPENING_VOUCHER_TYPES))[0][0]
    if company and not posting_date:
        frappe.has_permission('Company', 'read', doc=company, throw=True)
        posting_date = frappe.db.sql(
            '''SELECT MIN(posting_date) FROM `tabEx Student Opening Batch`
               WHERE company = %s AND docstatus = 1''', (company,))[0][0]
    return dict(company=company, posting_date=posting_date or today())


_AMOUNT = re.compile(r'^-?[\d,]*\.?\d*$')


def _parse_amount(raw):
    """``(value, error)`` for a CSV cell: blank → (None, None); accepts
    Indian grouping ("1,50,000") (pure)."""
    raw = (raw or '').strip()
    if not raw:
        return None, None
    if not _AMOUNT.match(raw) or raw in ('-', '.', '-.'):
        return None, _('"{0}" is not an amount').format(raw)
    value = flt(raw.replace(',', ''))
    if value < 0:
        return None, _('amounts cannot be negative ({0})').format(raw)
    return value, None


def _correct_opening_from_row(row):
    """``(amount, 'Dr' | 'Cr', error)`` from a CSV row's debit / credit
    columns. 0 in either means the opening should be nil (pure)."""
    debit, err_d = _parse_amount(row.get('debit'))
    credit, err_c = _parse_amount(row.get('credit'))
    if err_d or err_c:
        return None, None, err_d or err_c
    if debit is None and credit is None:
        return None, None, _('fill debit (student owes) or credit (advance); 0 for nil')
    if (debit or 0) > 0 and (credit or 0) > 0:
        return None, None, _('fill debit or credit, not both')
    if (credit or 0) > 0:
        return credit, 'Cr', None
    return debit or 0.0, 'Dr', None


def _student_index(students):
    """Lookup tables for matching CSV rows to Ex Students (pure)."""
    index = {'name': {}, 'student_id': {}, 'student_name': {}}
    for s in students:
        index['name'][s['name']] = s
        for key in ('student_id', 'student_name'):
            value = (s.get(key) or '').strip().lower()
            if value:
                index[key].setdefault(value, []).append(s)
    return index


def _match_student(row, index):
    """``(ex_student, error)`` for a CSV row (pure). By the Ex Student
    record first, then Student ID, then name — and only when exactly one
    enabled student of the company answers. Unlike the opening import,
    nobody is created: a correction is for a student who exists."""
    docname = (row.get('ex_student') or '').strip()
    if docname:
        s = index['name'].get(docname)
        if not s:
            return None, _('{0} is not an Ex Student of this company').format(docname)
        if s.get('is_disabled'):
            return None, _('{0} is disabled').format(docname)
        return s['name'], None
    for key, label in (('student_id', _('Student ID')), ('student_name', _('name'))):
        value = (row.get(key) or '').strip()
        if not value:
            continue
        found = [s for s in index[key].get(value.lower(), []) if not s.get('is_disabled')]
        if len(found) == 1:
            return found[0]['name'], None
        if not found:
            return None, _('no enabled Ex Student of this company has {0} "{1}"').format(label, value)
        return None, _('{0} "{1}" matches {2} students ({3}); use the ex_student column').format(
            label, value, len(found), ', '.join(sorted(s['name'] for s in found)))
    return None, _('give ex_student, student_id or student_name')


def _read_own_upload(file_url, doc):
    """The CSV the caller just uploaded for this adjustment — never another
    user's file, an old one, or one attached elsewhere."""
    files = frappe.get_all('File', filters={'file_url': file_url, 'owner': frappe.session.user},
                           fields=['name', 'creation', 'attached_to_doctype', 'attached_to_name'],
                           order_by='creation desc', limit=1)
    if not files:
        frappe.throw(_('Upload the CSV file from this form, then import it.'))
    f = files[0]
    if f.attached_to_doctype and (f.attached_to_doctype, f.attached_to_name) != (doc.doctype, doc.name):
        frappe.throw(_('That file belongs to another document. Upload the CSV again here.'))
    if get_datetime(f.creation) < add_to_date(now_datetime(), hours=-1):
        frappe.throw(_('That upload is more than an hour old. Upload the CSV again.'))
    file_doc = frappe.get_doc('File', f.name)
    content = file_doc.get_content()
    if isinstance(content, bytes):
        content = content.decode('utf-8-sig', errors='replace')
    if not f.attached_to_doctype:
        # Keep the source sheet with the voucher it produced.
        file_doc.db_set({'attached_to_doctype': doc.doctype, 'attached_to_name': doc.name})
    return content


@frappe.whitelist()
def import_adjustments_csv(adjustment, file_url):
    """Fill a draft Opening Adjustment from a CSV of CORRECT openings.

    Columns (header row, any order): ex_student or student_id or
    student_name; debit or credit (the correct opening; 0 for nil);
    remarks. A student whose opening is already right is skipped, not
    added. Returns ``{added, unchanged, errors}``."""
    doc = frappe.get_doc('Ex Student Opening Adjustment', adjustment)
    doc.check_permission('write')
    if doc.docstatus != 0:
        frappe.throw(_('Only a draft adjustment can be filled from a CSV'))
    if not doc.company:
        frappe.throw(_('Set the Company before importing'))

    rows = _parse_csv(_read_own_upload(file_url, doc))
    if not rows:
        frappe.throw(_('The CSV has no data rows'))

    index = _student_index(frappe.get_all(
        'Ex Student', filters={'company': doc.company},
        fields=['name', 'student_name', 'student_id', 'is_disabled']))
    already = {r.ex_student for r in doc.adjustments}
    errors, wanted = [], []
    for idx, row in enumerate(rows, start=2):  # row 1 = header
        name, err = _match_student(row, index)
        if not err:
            amount, dr_cr, err = _correct_opening_from_row(row)
        if not err and name in already:
            err = _('{0} is already in this adjustment').format(name)
        if err:
            errors.append(_('Row {0}: {1}').format(idx, err))
            continue
        already.add(name)
        wanted.append((name, amount, dr_cr, (row.get('remarks') or '').strip()))

    current = _current_openings([w[0] for w in wanted], doc.company)
    names = {s['name']: s['student_name'] for s in index['name'].values()}
    added = unchanged = 0
    for name, amount, dr_cr, remarks in wanted:
        cur_amount, cur_type = _split_signed(current.get(name, 0))
        debit, credit = _adjustment(current.get(name, 0), amount, dr_cr)
        if not debit and not credit:
            unchanged += 1
            continue
        doc.append('adjustments', {
            'ex_student': name, 'student_name': names.get(name),
            'current_amount': cur_amount, 'current_type': cur_type,
            'correct_amount': amount, 'correct_type': dr_cr,
            'debit': debit, 'credit': credit, 'change': _change_text(debit, credit),
            'remarks': remarks or None,
        })
        added += 1
    if added:
        doc.save()
    return {'added': added, 'unchanged': unchanged, 'errors': errors}
