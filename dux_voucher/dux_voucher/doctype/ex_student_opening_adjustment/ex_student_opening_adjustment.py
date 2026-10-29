"""Ex Student Opening Adjustment — correct some students' opening balances
without cancelling the Opening Batch they came in on.

An Opening Batch posts ONE netted journal entry for every student in it,
so the only way to change a single student's opening used to be to cancel
the whole batch (every student, receipts posted on top left dangling) and
enter it again. This voucher posts only the DIFFERENCE for the students
named on it:

* per student, one Ex Student Ledger Entry row — Dr to raise what the
  student owes, Cr to lower it — tagged as an opening row, so the opening
  shown everywhere is batch + adjustments;
* one Opening Entry journal (is_opening = Yes, same accounts as the batch:
  Ex-Students Receivable vs Temporary Opening) for the net. A pure move
  between two students nets to nil and posts no journal at all.

The user types the CORRECT opening; the difference is worked out against
the student's live opening when the voucher is saved, and checked again on
submit under a row lock, so two adjustments for one student can never
double-apply. Corrections stack in order: an earlier one cannot be
cancelled under a later one, exactly as a batch cannot be cancelled under
its corrections. Cancelling its journal cancels it
(``utils.on_journal_entry_cancel`` is doctype-agnostic).
"""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, formatdate, getdate

from dux_voucher.dux_voucher.api.ex_student_api import (
    _adjustment,
    _change_text,
    _current_openings,
    _signed,
    _split_signed,
    OPENING_VOUCHER_TYPES,
)
from dux_voucher.dux_voucher.api.tb_aggregate import queue_month_refresh
from dux_voucher.dux_voucher.doctype.ex_student_ledger_entry.ex_student_ledger_entry import (
    delete_cancelled_ledger_rows,
    posting_ledger_rows,
    require_cancel_right,
)
from dux_voucher.dux_voucher.api.utils import (
    _get_account_currency,
    _get_ex_student_accounts,
    _safe_cancel,
    _submit_doc,
)


def _money(amount):
    return frappe.format_value(abs(flt(amount)), {'fieldtype': 'Currency'})


def lock_students(names):
    """Serialise postings on these students until the transaction ends, so
    the opening read next is the latest committed one."""
    names = tuple({n for n in names if n})
    if names:
        frappe.db.sql('SELECT name FROM `tabEx Student` WHERE name IN %s FOR UPDATE', (names,))


class ExStudentOpeningAdjustment(Document):

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def insert(self, *args, **kwargs):
        """Clear the cancelled journal an amendment inherits before
        Frappe's link check refuses it (same as Ex Student Refund)."""
        if self.amended_from:
            self.backend_je = None
            self.is_posted = 0
        return super().insert(*args, **kwargs)

    # ------------------------------------------------------------------
    # Validate
    # ------------------------------------------------------------------
    def validate(self):
        if not self.company:
            frappe.throw(_('Company is required'))
        if not self.posting_date:
            frappe.throw(_('Posting Date is required'))
        if not (self.reason or '').strip():
            frappe.throw(_('Give the reason for this correction'))
        _get_ex_student_accounts(self.company)

        names = [r.ex_student for r in self.adjustments if r.ex_student]
        submitting = self._action == 'submit'
        if submitting:
            lock_students(names)
        students = {
            s.name: s for s in frappe.get_all(
                'Ex Student', filters={'name': ('in', names or [''])},
                fields=['name', 'student_name', 'company', 'is_disabled'])
        }
        # after the lock, read the latest committed rows, not this request's snapshot
        current = _current_openings(names, self.company, locking=submitting)
        facts = self._student_facts(names, locking=submitting)

        seen = set()
        total_debit = total_credit = 0.0
        for row in self.adjustments:
            s = students.get(row.ex_student)
            if not s:
                frappe.throw(_('Row {0}: Ex Student is required').format(row.idx))
            label = s.student_name or row.ex_student
            if s.company != self.company:
                frappe.throw(_('Row {0}: {1} belongs to {2}, not {3}').format(
                    row.idx, row.ex_student, s.company, self.company))
            if s.is_disabled:
                frappe.throw(_('Row {0}: {1} is disabled. Enable the student first.').format(
                    row.idx, row.ex_student))
            if row.ex_student in seen:
                frappe.throw(_('Row {0}: {1} appears twice. Keep one row per student.').format(
                    row.idx, row.ex_student))
            seen.add(row.ex_student)
            f = facts.get(row.ex_student, {})
            if f.get('other_company'):
                frappe.throw(_(
                    'Row {0}: {1} still has postings under {2}: the student was moved to {3} '
                    'after posting. Move the student back to {2} to correct them there.'
                ).format(row.idx, label, f['other_company'], self.company))
            if f.get('first_opening') and getdate(self.posting_date) < getdate(f['first_opening']):
                frappe.throw(_(
                    'Row {0}: the opening of {1} is dated {2}. Date this correction on or after it, '
                    'so no statement shows the correction without the opening it corrects.'
                ).format(row.idx, label, formatdate(f['first_opening'])))
            if row.correct_amount is None or row.correct_amount == '':
                # never read a forgotten amount as "make the opening nil"
                frappe.throw(_('Row {0}: enter the correct opening of {1} (0 to make it nil).').format(
                    row.idx, label))
            if flt(row.correct_amount) < 0:
                frappe.throw(_('Row {0}: Correct Opening cannot be negative. Use Cr for an advance.').format(row.idx))
            row.correct_type = row.correct_type or 'Dr'

            now = current.get(row.ex_student, 0)
            if submitting and row.current_type and abs(
                    _signed(row.current_amount, row.current_type) - now) > 0.005:
                amount, dr_cr = _split_signed(now)
                frappe.throw(_(
                    'Row {0}: the opening of {1} has changed to {2} {3} since this was saved. '
                    'Click Refresh Openings, check the figures, save, then submit.'
                ).format(row.idx, label, _money(amount), dr_cr))

            row.student_name = s.student_name
            row.current_amount, row.current_type = _split_signed(now)
            row.debit, row.credit = _adjustment(now, row.correct_amount, row.correct_type)
            row.change = _change_text(row.debit, row.credit)
            if not row.debit and not row.credit:
                frappe.throw(_(
                    'Row {0}: the opening of {1} is already {2} {3}. Remove the row.'
                ).format(row.idx, label, _money(row.current_amount), row.current_type))
            self._refuse_written_off_advance(row, label, f, flt(row.debit) - flt(row.credit))
            total_debit += flt(row.debit)
            total_credit += flt(row.credit)

        self.total_debit = total_debit
        self.total_credit = total_credit
        self.net_amount = flt(total_debit - total_credit, 2)

    def _student_facts(self, names, locking=False):
        """Per student, in one query: balance in this company, write-offs,
        first opening date, and any company the rows sit in other than this
        one."""
        names = tuple({n for n in names if n})
        if not names:
            return {}
        out = {}
        for s, company, balance, written_off, first_opening in frappe.db.sql(
            '''
            SELECT ex_student, company, SUM(debit - credit),
                   SUM(CASE WHEN voucher_type = 'Ex Student Writeoff' THEN credit - debit ELSE 0 END),
                   MIN(CASE WHEN voucher_type IN %s THEN posting_date END)
            FROM `tabEx Student Ledger Entry`
            WHERE ex_student IN %s AND is_cancelled = 0
            GROUP BY ex_student, company
            ''' + (' LOCK IN SHARE MODE' if locking else ''), (OPENING_VOUCHER_TYPES, names)):
            f = out.setdefault(s, {})
            if company == self.company:
                f.update(balance=flt(balance), written_off=flt(written_off), first_opening=first_opening)
            else:
                f['other_company'] = company
        return out

    def _refuse_written_off_advance(self, row, label, facts, change):
        """A correction that leaves a student in credit while part of their
        dues was written off would turn the write-off into a refundable
        advance: correct the write-off first."""
        after = flt(facts.get('balance')) + flt(change)
        if after < -0.005 and flt(facts.get('written_off')) > 0.005:
            frappe.throw(_(
                'Row {0}: this would leave {1} with an advance of {2}, but {3} of their dues was '
                'written off. Cancel or amend the write-off first, so the expense is corrected '
                'instead of becoming an advance that could be refunded.'
            ).format(row.idx, label, _money(after), _money(facts.get('written_off'))))

    def before_submit(self):
        if not self.adjustments:
            frappe.throw(_('Add at least one student before submitting'))

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    def on_submit(self):
        je_name = self._create_journal_entry()
        self._insert_ledger_entries()
        self.db_set('backend_je', je_name, update_modified=False)
        self.db_set('is_posted', 1, update_modified=False)
        self._recompute_student_balances()
        if je_name:
            queue_month_refresh(self.company, self.posting_date)

    def _create_journal_entry(self):
        net = flt(self.net_amount, 2)
        if abs(net) < 0.005:
            # Money moved between students only: nothing changes in the GL.
            return None
        receivable_account, opening_account = _get_ex_student_accounts(self.company)
        currency = _get_account_currency(receivable_account, self.company)

        je = frappe.new_doc('Journal Entry')
        je.voucher_type = 'Opening Entry'
        je.is_opening = 'Yes'
        je.company = self.company
        je.posting_date = self.posting_date
        je.user_remark = _('Ex-student opening correction {0}: {1}').format(self.name, self.reason)
        je.custom_source_voucher_doctype = self.doctype
        je.custom_source_voucher = self.name

        dr, cr = (receivable_account, opening_account) if net > 0 else (opening_account, receivable_account)
        je.append('accounts', {'account': dr, 'account_currency': currency,
                               'debit_in_account_currency': abs(net), 'credit_in_account_currency': 0})
        je.append('accounts', {'account': cr, 'account_currency': currency,
                               'debit_in_account_currency': 0, 'credit_in_account_currency': abs(net)})
        _submit_doc(je)
        return je.name

    def _insert_ledger_entries(self):
        with posting_ledger_rows(self):
            for row in self.adjustments:
                ledger = frappe.new_doc('Ex Student Ledger Entry')
                ledger.ex_student = row.ex_student
                ledger.company = self.company
                ledger.posting_date = self.posting_date
                ledger.debit = flt(row.debit)
                ledger.credit = flt(row.credit)
                ledger.voucher_type = self.doctype
                ledger.voucher_no = self.name
                ledger.remarks = row.remarks or self.reason
                ledger.is_cancelled = 0
                ledger.insert(ignore_permissions=True)

    def on_trash(self):
        delete_cancelled_ledger_rows(self)

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------
    def before_cancel(self):
        """Corrections stack: a later one was worked out on top of this one.
        Cancelling this first would leave the later one's difference
        applied to a figure nobody typed."""
        require_cancel_right(self)
        names = [r.ex_student for r in self.adjustments if r.ex_student]
        lock_students(names)
        later = frappe.db.sql_list(
            '''
            SELECT DISTINCT l.voucher_no FROM `tabEx Student Ledger Entry` l
            WHERE l.voucher_type = %(dt)s AND l.is_cancelled = 0 AND l.voucher_no != %(me)s
              AND l.ex_student IN %(students)s
              AND l.creation > (SELECT MAX(m.creation) FROM `tabEx Student Ledger Entry` m
                                WHERE m.voucher_type = %(dt)s AND m.voucher_no = %(me)s)
            ORDER BY l.voucher_no LOCK IN SHARE MODE
            ''', dict(dt=self.doctype, me=self.name, students=tuple(names) or ('',)))
        if later:
            frappe.throw(_(
                'These students were corrected again later by {0}. Cancel the later '
                'correction first, or post a new correction instead of cancelling this one.'
            ).format(', '.join(later)), title=_('A later correction depends on this one'))
        facts = self._student_facts(names, locking=True)
        for row in self.adjustments:
            label = row.student_name or row.ex_student
            self._refuse_written_off_advance(row, label, facts.get(row.ex_student, {}),
                                             flt(row.credit) - flt(row.debit))

    def on_cancel(self):
        if self.backend_je:
            _safe_cancel('Journal Entry', self.backend_je)
        frappe.db.sql(
            '''
            UPDATE `tabEx Student Ledger Entry`
            SET is_cancelled = 1
            WHERE voucher_type = %s AND voucher_no = %s
            ''',
            (self.doctype, self.name),
        )
        self.db_set('is_posted', 0, update_modified=False)
        self._recompute_student_balances()
        if self.backend_je:
            queue_month_refresh(self.company, self.posting_date)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _recompute_student_balances(self):
        for row in self.adjustments:
            if row.ex_student and frappe.db.exists('Ex Student', row.ex_student):
                frappe.get_doc('Ex Student', row.ex_student).recompute_opening_balance()
