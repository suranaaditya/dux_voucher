"""Unit tests for a party ledger's journal / payment drill-down (api/reports_api.py).

GL ``against`` lists only the OPPOSITE side of a voucher, so a bill booked
net of TDS (Dr expense, Cr TDS, Cr the supplier's net) read "To <expense>"
with nothing to open and the TDS never showed, while TDS taken on a payment
(the opposite side) did. A party's journal and payment rows now open to the
whole voucher, Tally's "as per details", where the voucher is the party's
own. On a journal, accounts beside the party count as its own only on a
bill: on the side its bills post, in a journal that moves no money, with no
other party on it. A payment entry is one party's payment, so neither the
side nor the money check applies to it. Another party on the row's own side
or on a journal that moves money,
other heads paid or received beside the party, a salary sheet or an opening
entry return None and read as before. Parties opposite a row alone on its
side are named: a contra between creditors, a claim that also pays a vendor.

Lines are given in the order the drill-down query returns them, by account;
the drill-down keeps that order within each side. These cover the pure part,
_voucher_makeup, and the lookups behind it; the page output is exercised
read-only against production.
"""

import unittest
from unittest import mock

from dux_voucher.dux_voucher.api import reports_api
from dux_voucher.dux_voucher.api.reports_api import _voucher_makeup

CRED, DEBT = "Sundry Creditors - J", "Sundry Debtors - J"
SUP, SUP2, SUP3 = ("Supplier", "SUP-1"), ("Supplier", "SUP-2"), ("Supplier", "SUP-3")
CUS, EMP, STU = ("Customer", "CUS-1"), ("Employee", "E-1"), ("Student", "STU-1")
NAMES = {SUP: "Caterer", SUP2: "Printer", SUP3: "Electrician"}
BANKS = {"Bank - J", "Bank OD - J"}


def _gl(account, debit=0, credit=0, party=("", "")):
    return {"account": account, "debit": debit, "credit": credit,
            "party_type": party[0], "party": party[1]}


def _mk(lines, account, party, dr, cr, bill_side="Cr", **kw):
    """A supplier's or an employee's bills post on Cr, the default here."""
    kw.setdefault("bank_accounts", BANKS)
    return _voucher_makeup(lines, account, party, dr, cr, NAMES, bill_side, **kw)


def _view(rows):
    return [(r["label"], r["amount"], r["side"]) for r in rows]


def _signed(rows):
    """Net of a drill-down, Dr positive."""
    return round(sum(r["amount"] if r["side"] == "Dr" else -r["amount"] for r in rows), 2)


class TestVoucherMakeup(unittest.TestCase):

    # ── what the drill-down now shows ────────────────────────────────

    def test_bill_booked_net_of_tds_shows_the_tds(self):
        # The reported case: the TDS is credited on the supplier's own side.
        lines = [_gl("Canteen Expenses - J", debit=11182), _gl(CRED, credit=11075, party=SUP),
                 _gl("TDS 194C - J", credit=107)]
        out = _mk(lines, CRED, SUP, 0, 11075)
        self.assertEqual(_view(out), [("Canteen Expenses - J", 11182, "Dr"), ("TDS 194C - J", 107, "Cr")])
        self.assertEqual(_signed(out), 11075)   # adds up to the supplier's credit

    def test_every_deduction_on_a_bill_shows(self):
        # A canteen bill less TDS and an electricity recovery: the row reads 539.
        lines = [_gl("Canteen Expenses - J", debit=1984), _gl("Electricity Charges - J", credit=1426),
                 _gl(CRED, credit=539, party=SUP), _gl("TDS 194C - J", credit=19)]
        out = _mk(lines, CRED, SUP, 0, 539)
        self.assertEqual(_view(out), [("Canteen Expenses - J", 1984, "Dr"),
                                      ("Electricity Charges - J", 1426, "Cr"),
                                      ("TDS 194C - J", 19, "Cr")])
        self.assertEqual(_signed(out), 539)

    def test_a_customer_bill_shows_the_tds_it_withheld(self):
        # A customer's bills post on Dr: the TDS it withheld sits beside it.
        lines = [_gl("Hall Rent - J", credit=10000), _gl(DEBT, debit=9900, party=CUS),
                 _gl("TDS Receivable - J", debit=100)]
        out = _mk(lines, DEBT, CUS, 9900, 0, bill_side="Dr")
        self.assertEqual(_view(out), [("Hall Rent - J", 10000, "Cr"), ("TDS Receivable - J", 100, "Dr")])
        self.assertEqual(_signed(out), -9900)

    def test_tds_on_an_advance_reads_as_before(self):
        # TDS on the opposite side was already shown under "Various": the
        # same lines, in the same order.
        lines = [_gl("Foundation - J", credit=2450000), _gl(CRED, debit=2500000, party=SUP),
                 _gl("TDS 194C - J", credit=50000)]
        out = _mk(lines, CRED, SUP, 2500000, 0)
        self.assertEqual(_view(out), [("Foundation - J", 2450000, "Cr"), ("TDS 194C - J", 50000, "Cr")])
        self.assertEqual(_signed(out), -2500000)

    def test_a_various_drill_down_keeps_its_order(self):
        # A student's fee journal: the heads come in account order, as the
        # "Various" drill-down always listed them, not largest first.
        lines = [_gl("Hostel Caution Money - J", credit=5000), _gl("Hostel Fee - J", credit=110000),
                 _gl("Student Ledger - J", debit=115000, party=STU)]
        out = _mk(lines, "Student Ledger - J", STU, 115000, 0, bill_side="Dr")
        self.assertEqual(_view(out), [("Hostel Caution Money - J", 5000, "Cr"),
                                      ("Hostel Fee - J", 110000, "Cr")])

    def test_a_payment_entry_is_its_partys_own(self):
        # A payment entry pays one party: its bank charges are this payment's,
        # and the bank on it does not hold it back.
        lines = [_gl("Bank - J", credit=10050), _gl("Bank Charges - J", debit=50),
                 _gl(CRED, debit=10000, party=SUP)]
        out = _mk(lines, CRED, SUP, 10000, 0, payment_entry=True)
        self.assertEqual(_view(out), [("Bank - J", 10050, "Cr"), ("Bank Charges - J", 50, "Dr")])
        self.assertEqual(_signed(out), -10000)
        # The same lines in a journal read as before (see the next section).
        self.assertIsNone(_mk(lines, CRED, SUP, 10000, 0))

    def test_counter_parties_are_named(self):
        # The old drill-down skipped every line on the party's own account,
        # so a "Various" between two creditors opened empty.
        lines = [_gl(CRED, debit=1000, party=SUP), _gl(CRED, credit=600, party=SUP2),
                 _gl(CRED, credit=400, party=("Supplier", "SUP-9"))]
        out = _mk(lines, CRED, SUP, 1000, 0)
        self.assertEqual(_view(out), [(CRED + "  ·  Printer", 600, "Cr"),
                                      (CRED + "  ·  SUP-9", 400, "Cr")])   # id when no name
        self.assertEqual(out[0]["party"], "SUP-2")
        # The two receiving creditors share their side: they read as before.
        self.assertIsNone(_mk(lines, CRED, SUP2, 0, 600))
        # Two creditors on each side: every row shares its side, and none
        # may name the other three.
        lines = [_gl(CRED, debit=600, party=SUP), _gl(CRED, debit=400, party=SUP2),
                 _gl(CRED, credit=700, party=SUP3), _gl(CRED, credit=300, party=("Supplier", "SUP-9"))]
        self.assertIsNone(_mk(lines, CRED, SUP, 600, 0))
        self.assertIsNone(_mk(lines, CRED, SUP3, 0, 700))

    def test_a_transfer_between_suppliers_less_tds(self):
        # The debited supplier's figure is wholly what the other received and
        # the TDS, so it opens. On the receiving side the TDS cannot be told
        # apart as its own, so that row reads as before.
        lines = [_gl(CRED, debit=1000, party=SUP), _gl(CRED, credit=990, party=SUP2),
                 _gl("TDS 194C - J", credit=10)]
        out = _mk(lines, CRED, SUP, 1000, 0)
        self.assertEqual(_view(out), [(CRED + "  ·  Printer", 990, "Cr"), ("TDS 194C - J", 10, "Cr")])
        self.assertEqual(_signed(out), -1000)
        self.assertIsNone(_mk(lines, CRED, SUP2, 0, 990))

    def test_an_expense_claim_names_the_vendor_it_paid(self):
        # A staff member's expense claim that also pays a hotel: the
        # claimant's row opens to the claim's heads and the hotel it paid.
        # (The hotel's own row reads as before, see below.)
        claimant = ("Supplier", "SUP-7")
        lines = [_gl("Repairs Building - J", debit=1469), _gl("Repairs Vehicle - J", debit=220),
                 _gl("Staff Welfare - J", debit=560), _gl(CRED, debit=1000, party=SUP2),
                 _gl(CRED, credit=3249, party=claimant)]
        out = _mk(lines, CRED, claimant, 0, 3249)
        self.assertEqual(_view(out), [("Repairs Building - J", 1469, "Dr"), ("Repairs Vehicle - J", 220, "Dr"),
                                      ("Staff Welfare - J", 560, "Dr"), (CRED + "  ·  Printer", 1000, "Dr")])
        self.assertEqual(_signed(out), 3249)

    def test_party_with_more_lines_on_the_voucher(self):
        # A payment split over three bills: each row is one of three lines.
        lines = [_gl("Bank - J", credit=594), _gl(CRED, debit=600, party=SUP), _gl("TDS 194C - J", credit=6)]
        out = _mk(lines, CRED, SUP, 100, 0)
        self.assertEqual(_view(out), [("Bank - J", 594, "Cr"), ("TDS 194C - J", 6, "Cr"),
                                      (CRED + "  ·  Caterer", 500, "Dr")])
        self.assertEqual(_signed(out), -100)
        # Without a deduction the split rows read as they always have.
        lines = [_gl("Bank - J", credit=600), _gl(CRED, debit=600, party=SUP)]
        self.assertIsNone(_mk(lines, CRED, SUP, 100, 0))

    def test_a_bill_settled_in_the_same_journal(self):
        # Billed and settled from a staff imprest in one journal: the bill
        # half opens to the head, the settlement and the imprest.
        lines = [_gl("Repairs - J", debit=100), _gl("Staff Imprest - J", credit=100),
                 _gl(CRED, debit=100, credit=100, party=SUP)]
        out = _mk(lines, CRED, SUP, 0, 100)
        self.assertEqual(_view(out), [("Repairs - J", 100, "Dr"), (CRED + "  ·  Caterer", 100, "Dr"),
                                      ("Staff Imprest - J", 100, "Cr")])
        self.assertEqual(_signed(out), 100)
        # Paid from a bank in the same journal it reads as before: the bank
        # line is the journal's whole payment.
        lines = [_gl("Bank - J", credit=100), _gl("Repairs - J", debit=100),
                 _gl(CRED, debit=100, credit=100, party=SUP)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 100))

    def test_five_accounts_on_the_party_side_are_still_listed(self):
        lines = [_gl("Canteen Expenses - J", debit=10000), _gl("Electricity Charges - J", credit=900),
                 _gl("Rent Recovery - J", credit=2000), _gl("Round Off - J", credit=0.4),
                 _gl(CRED, credit=6699.6, party=SUP), _gl("TDS 194C - J", credit=100),
                 _gl("Water Charges - J", credit=300)]
        out = _mk(lines, CRED, SUP, 0, 6699.6)
        self.assertEqual(len(out), 6)
        self.assertIn(("TDS 194C - J", 100, "Cr"), _view(out))
        self.assertEqual(_signed(out), 6699.6)

    def test_amounts_are_rounded(self):
        lines = [_gl("Canteen Expenses - J", debit=100.004), _gl(CRED, credit=98.9991, party=SUP),
                 _gl("TDS 194C - J", credit=1.0049)]
        out = _mk(lines, CRED, SUP, 0, 98.9991)
        self.assertEqual([r["amount"] for r in out], [100.0, 1.0])

    def test_every_drill_down_adds_up_to_its_row(self):
        pay = "Salary Payable - J"
        cases = [
            ([_gl("Canteen Expenses - J", debit=7128), _gl(CRED, credit=7060, party=SUP),
              _gl("TDS 194C - J", credit=68)], CRED, SUP, (0, 7060)),
            ([_gl("Building WIP - J", debit=3658454), _gl(CRED, credit=3646446, party=SUP),
              _gl("TDS 194C - J", credit=12008)], CRED, SUP, (0, 3646446)),
            ([_gl("Bank - J", credit=60000), _gl("Bank OD - J", credit=39000),
              _gl(CRED, debit=100000, party=SUP), _gl("TDS 194C - J", credit=1000)], CRED, SUP, (100000, 0)),
            ([_gl("Provident Fund - J", credit=3000), _gl("Salary - J", debit=60000),
              _gl(pay, credit=52000, party=EMP), _gl("TDS 192 - J", credit=5000)], pay, EMP, (0, 52000)),
        ]
        for lines, account, party, (dr, cr) in cases:
            out = _mk(lines, account, party, dr, cr)
            self.assertTrue(out)
            self.assertAlmostEqual(_signed(out), round(cr - dr, 2), places=2)

    # ── vouchers that are not the party's own read as before ─────────

    def test_a_plain_two_line_voucher_reads_as_before(self):
        lines = [_gl("Foundation - J", credit=6424), _gl(CRED, debit=6424, party=SUP)]
        self.assertIsNone(_mk(lines, CRED, SUP, 6424, 0))

    def test_a_shared_payment_reads_as_before(self):
        # One transfer paying three suppliers: the other payees are no
        # business of this supplier's statement.
        lines = [_gl("Foundation - J", credit=95910), _gl(CRED, debit=34591, party=SUP2),
                 _gl(CRED, debit=22319, party=SUP), _gl(CRED, debit=39000, party=SUP3)]
        self.assertIsNone(_mk(lines, CRED, SUP, 22319, 0))
        # Less TDS: two lines opposite and no money moved, so only the
        # shared side holds it back.
        lines = [_gl("Foundation - J", credit=94910), _gl(CRED, debit=34591, party=SUP2),
                 _gl(CRED, debit=22319, party=SUP), _gl(CRED, debit=39000, party=SUP3),
                 _gl("TDS 194C - J", credit=1000)]
        self.assertIsNone(_mk(lines, CRED, SUP, 22319, 0))
        self.assertIsNone(_mk(lines, CRED, SUP2, 34591, 0))

    def test_a_shared_transfer_with_a_self_cheque_reads_as_before(self):
        # The account beside the suppliers is not this supplier's, and the
        # transfer's total would give the other supplier's figure away.
        lines = [_gl("Foundation - J", credit=1487205), _gl(CRED, debit=200000, party=SUP2),
                 _gl(CRED, debit=461211, party=SUP), _gl("Yourself Cheque - J", debit=825994)]
        self.assertIsNone(_mk(lines, CRED, SUP, 461211, 0))
        self.assertIsNone(_mk(lines, CRED, SUP2, 200000, 0))

    def test_a_payment_beside_a_self_cheque_reads_as_before(self):
        # Alone on its side, the supplier still was not paid the self cheque.
        lines = [_gl("Foundation - J", credit=1287205), _gl(CRED, debit=461211, party=SUP),
                 _gl("Yourself Cheque - J", debit=825994)]
        self.assertIsNone(_mk(lines, CRED, SUP, 461211, 0))

    def test_a_party_and_head_payment_reads_as_before(self):
        # One payment voucher paying a supplier and two heads from one bank
        # line: the heads beside the supplier are what else it paid, and the
        # bank's total would give them away.
        lines = [_gl("Bank - J", credit=23325), _gl("Office Expenses - J", debit=750),
                 _gl(CRED, debit=3075, party=SUP), _gl("Visiting Faculty - J", debit=19500)]
        self.assertIsNone(_mk(lines, CRED, SUP, 3075, 0))

    def test_a_payment_voucher_crediting_a_supplier_reads_as_before(self):
        # A Party + Head payment voucher that credits a supplier beside its
        # bank line: the bank's total is what the voucher paid, not the
        # supplier's.
        lines = [_gl("Bank - J", credit=16132), _gl("Office Expenses - J", debit=6632),
                 _gl(CRED, credit=500, party=SUP), _gl("Visiting Faculty - J", debit=10000)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 500))

    def test_a_receipt_with_other_heads_reads_as_before(self):
        # The mirror for a customer: its receipts post on Cr, beside the other
        # receipts of the same voucher.
        lines = [_gl("Bank - J", debit=7000), _gl("Hall Rent - J", credit=2000),
                 _gl(DEBT, credit=5000, party=CUS)]
        self.assertIsNone(_mk(lines, DEBT, CUS, 0, 5000, bill_side="Dr"))

    def test_a_supplier_refund_received_with_other_heads_reads_as_before(self):
        # A supplier paying money back posts on its bill side (Cr). Received
        # in a Party + Head receipt voucher beside the day's other receipts,
        # what sits beside it is those receipts, and opposite the bank total.
        lines = [_gl("Bank - J", debit=25300), _gl("Hostel Fee - J", credit=20000),
                 _gl("Misc Income - J", credit=300), _gl(CRED, credit=5000, party=SUP)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 5000))
        # Into an overdraft (a Bank account under Liabilities), the same.
        lines[0] = _gl("Bank OD - J", debit=25300)
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 5000))
        # Made by a receipt voucher, whatever its receiving account is typed.
        lines[0] = _gl("Collections - J", debit=25300)
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 5000, money_voucher=True))

    def test_a_refund_to_a_customer_with_other_heads_reads_as_before(self):
        # A customer refunded posts on its bill side (Dr), beside the other
        # heads a Party + Head payment voucher paid from the same bank line.
        lines = [_gl("Bank - J", credit=25250), _gl("Office Expenses - J", debit=750),
                 _gl(DEBT, debit=5000, party=CUS), _gl("Visiting Faculty - J", debit=19500)]
        self.assertIsNone(_mk(lines, DEBT, CUS, 5000, 0, bill_side="Dr"))

    def test_an_employee_returning_an_advance_with_other_heads_reads_as_before(self):
        pay = "Staff Advances - J"
        lines = [_gl("Hostel Fee - J", credit=20000), _gl("Petty Cash - J", debit=23000),
                 _gl(pay, credit=3000, party=EMP)]
        self.assertIsNone(_mk(lines, pay, EMP, 0, 3000, money_voucher=True))

    def test_a_debit_note_reads_as_before(self):
        # A supplier debited in a journal: the lines beside it are read as what
        # else the journal paid, so the TDS reversed on a debit note stays
        # where it was, out of the drill-down.
        lines = [_gl("Repairs - J", credit=1000), _gl(CRED, debit=990, party=SUP),
                 _gl("TDS 194C - J", debit=10)]
        self.assertIsNone(_mk(lines, CRED, SUP, 990, 0))

    def test_a_vendor_paid_inside_an_expense_claim_reads_as_before(self):
        # A staff member's expense claim that also pays a hotel: the claim's
        # heads and the claimant's whole figure are not the hotel's business.
        claimant = ("Supplier", "SUP-7")
        lines = [_gl("Repairs Building - J", debit=1469), _gl("Repairs Vehicle - J", debit=220),
                 _gl("Staff Welfare - J", debit=560), _gl(CRED, debit=1000, party=SUP2),
                 _gl(CRED, credit=3249, party=claimant)]
        self.assertIsNone(_mk(lines, CRED, SUP2, 1000, 0))

    def test_another_party_in_a_money_voucher_reads_as_before(self):
        # A Party + Head receipt voucher takes one customer's fee and pays
        # another a refund out of the same bank line. Alone on its side, the
        # customer still has no business with the other's refund: the bank
        # line is the voucher's whole total.
        cus2 = ("Customer", "CUS-2")
        lines = [_gl("Bank - J", debit=4000), _gl(DEBT, debit=1000, party=cus2),
                 _gl(DEBT, credit=5000, party=CUS)]
        self.assertIsNone(_mk(lines, DEBT, CUS, 0, 5000, bill_side="Dr"))
        self.assertIsNone(_mk(lines, DEBT, cus2, 1000, 0, bill_side="Dr"))
        # Made by a receipt voucher, whatever its receiving account is typed.
        lines[0] = _gl("Collections - J", debit=4000)
        self.assertIsNone(_mk(lines, DEBT, CUS, 0, 5000, bill_side="Dr", money_voucher=True))
        # The payment voucher's mirror: one supplier paid, another's credit
        # set off against the same bank line.
        lines = [_gl("Bank - J", credit=9500), _gl(CRED, debit=10000, party=SUP),
                 _gl(CRED, credit=500, party=SUP2)]
        self.assertIsNone(_mk(lines, CRED, SUP, 10000, 0))

    def test_a_bill_beside_a_payment_to_another_supplier_reads_as_before(self):
        # One journal books one supplier's bill net of TDS and pays another:
        # neither statement may carry the other supplier's figure.
        lines = [_gl("Imprest - J", credit=1000), _gl("Repairs - J", debit=5000),
                 _gl(CRED, credit=4950, party=SUP2), _gl(CRED, debit=1000, party=SUP),
                 _gl("TDS 194C - J", credit=50)]
        self.assertIsNone(_mk(lines, CRED, SUP2, 0, 4950))
        self.assertIsNone(_mk(lines, CRED, SUP, 1000, 0))

    def test_a_party_whose_lines_cancel_still_shares_the_voucher(self):
        # Two suppliers' bills net of TDS, one of them also paid in the same
        # journal: its two lines on one account sum to nothing, yet the
        # payment and half the TDS are its, not the other supplier's.
        lines = [_gl("Imprest - J", credit=990), _gl("Repairs - J", debit=2000),
                 _gl(CRED, credit=990, party=SUP), _gl(CRED, debit=990, credit=990, party=SUP2),
                 _gl("TDS 194C - J", credit=20)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 990))
        # Without TDS, the same: the other supplier's payment is not this one's.
        lines = [_gl("Imprest - J", credit=1000), _gl("Repairs - J", debit=2000),
                 _gl(CRED, credit=1000, party=SUP), _gl(CRED, debit=1000, credit=1000, party=SUP2)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 1000))

    def test_one_bill_for_two_suppliers_reads_as_before(self):
        # Whose TDS it is cannot be told: listing it would show one supplier
        # a deduction that may be all the other's.
        lines = [_gl("Repairs - J", debit=3000), _gl(CRED, credit=1000, party=SUP),
                 _gl(CRED, credit=1980, party=SUP2), _gl("TDS 194C - J", credit=20)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 1000))
        self.assertIsNone(_mk(lines, CRED, SUP2, 0, 1980))

    def test_an_employee_on_a_payroll_with_colleagues_reads_as_before(self):
        pay = "Salary Payable - J"
        lines = [_gl("Provident Fund - J", credit=10000), _gl("Salary - J", debit=300000),
                 _gl(pay, credit=50000, party=EMP), _gl(pay, credit=220000, party=("Employee", "E-2")),
                 _gl("TDS 192 - J", credit=20000)]
        self.assertIsNone(_mk(lines, pay, EMP, 0, 50000))

    def test_a_salary_sheet_reads_as_before(self):
        # A supplier paid out of staff salaries is one line of a sheet whose
        # other accounts (staff loans by name among them) are not its own.
        lines = [_gl("A Staff Member - J", credit=3000), _gl("Hostel Recovery - J", credit=3800),
                 _gl("Net Pay - J", credit=80000), _gl("Professional Tax - J", credit=2000),
                 _gl("Provident Fund - J", credit=6000), _gl("Salary - J", debit=100000),
                 _gl(CRED, credit=200, party=SUP), _gl("TDS 192 - J", credit=5000)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 200))

    def test_an_unknown_bill_side_reads_as_before(self):
        # A party type that is neither Payable nor Receivable: on a journal,
        # no account beside the party is taken as its own.
        lines = [_gl("Canteen Expenses - J", debit=11182), _gl(CRED, credit=11075, party=SUP),
                 _gl("TDS 194C - J", credit=107)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 11075, bill_side=None))

    def test_a_single_counter_account_is_left_to_the_various_rule(self):
        # GL "against" is a comma-joined list, so ONE counter account whose
        # own name holds a comma reads "Various". Nothing to add here, so the
        # row keeps the opposite-side drill-down, which opens it as before.
        lines = [_gl("Public School, City - J", debit=57629.58), _gl(CRED, credit=57629.58, party=SUP)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 57629.58))

    def test_lines_that_net_to_nothing_are_dropped(self):
        lines = [_gl("Canteen Expenses - J", debit=0.1 + 0.2), _gl("Round Off - J", credit=0.001),
                 _gl(CRED, credit=0.3, party=SUP), _gl("TDS 194C - J", debit=5, credit=5)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 0.3))

    def test_a_zero_row_has_nothing_to_open(self):
        lines = [_gl("Canteen Expenses - J", debit=10), _gl(CRED, credit=9, party=SUP),
                 _gl("TDS 194C - J", credit=1)]
        self.assertIsNone(_mk(lines, CRED, SUP, 0, 0))
        self.assertIsNone(_mk([], CRED, SUP, 0, 9))


class TestLookups(unittest.TestCase):

    def test_bill_side_follows_the_party_type(self):
        account_types = {"Supplier": "Payable", "Employee": "Payable",
                         "Customer": "Receivable", "Student": "Receivable"}

        def cached(doctype, name, fieldname):
            self.assertEqual((doctype, fieldname), ("Party Type", "account_type"))
            return account_types.get(name)

        with mock.patch.object(reports_api.frappe, "get_cached_value", side_effect=cached, create=True):
            self.assertEqual(reports_api._party_bill_side("Supplier"), "Cr")
            self.assertEqual(reports_api._party_bill_side("Employee"), "Cr")
            self.assertEqual(reports_api._party_bill_side("Customer"), "Dr")
            self.assertEqual(reports_api._party_bill_side("Student"), "Dr")
            self.assertIsNone(reports_api._party_bill_side("Unknown"))
            self.assertIsNone(reports_api._party_bill_side(None))

    def test_bank_accounts_are_read_by_type_alone(self):
        # Overdrafts are typed Bank under Liabilities; Cash is typed on
        # income, expense and tax heads too, so it is not read.
        def get_all(doctype, filters=None, pluck=None):
            self.assertEqual((doctype, pluck), ("Account", "name"))
            self.assertEqual(filters, {"name": ["in", ["Bank OD - J", "Petty Cash - J", "TDS 194C - J"]],
                                       "account_type": "Bank"})
            return ["Bank OD - J"]

        with mock.patch.object(reports_api.frappe, "get_all", side_effect=get_all, create=True) as m:
            self.assertEqual(reports_api._bank_accounts({"TDS 194C - J", "Petty Cash - J", "Bank OD - J"}),
                             {"Bank OD - J"})
            self.assertEqual(reports_api._bank_accounts(set()), set())   # no query for nothing
            self.assertEqual(m.call_count, 1)


if __name__ == "__main__":
    unittest.main()
