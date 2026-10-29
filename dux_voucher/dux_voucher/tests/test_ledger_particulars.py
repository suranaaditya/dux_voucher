"""Unit tests for how purchases read in the ledgers (api/reports_api.py).

A supplier's invoice reads as WHAT was bought — the heads behind it, not
the "Stock / Asset Received But Not Billed" clearing account it posts to —
and a GRN reads as WHO it came from, with its items for a narration. These
cover the pure parts: which head a line bought into, the invoice's make-up
for the drill-down, the label, and the items summary. The pages' end-to-end
output is exercised on the dev site and read-only against production.
"""

import unittest

from dux_voucher.dux_voucher.api.reports_api import (
    _heads_label,
    _invoice_makeup,
    _items_summary,
    _resolve_line_head,
)

CLEAR = {"Asset Received But Not Billed - J", "Stock Received But Not Billed - J"}


def _line(**kw):
    base = {"expense_account": "", "grn_account": "", "is_fixed_asset": 0, "asset_category": "",
            "item_code": "X", "item_group": "G", "amount": 100}
    base.update(kw)
    return base


class TestLineHead(unittest.TestCase):

    def test_direct_invoice_line_is_its_own_head(self):
        self.assertEqual(_resolve_line_head(_line(expense_account="Freight - J"), CLEAR, {}, {}, {}), "Freight - J")

    def test_grn_line_answers_for_a_clearing_line(self):
        ln = _line(expense_account="Asset Received But Not Billed - J", grn_account="Computer & Accessories - J")
        self.assertEqual(_resolve_line_head(ln, CLEAR, {}, {}, {}), "Computer & Accessories - J")

    def test_asset_category_before_item_default(self):
        # The item default on asset items is a REPAIRS head — wrong for a purchase.
        ln = _line(expense_account="Asset Received But Not Billed - J", is_fixed_asset=1,
                   asset_category="Computers")
        self.assertEqual(_resolve_line_head(ln, CLEAR, {"Computers": "Computer & Accessories - J"},
                                            {"X": "Repairs & Maintenance Computers - J"}, {}),
                         "Computer & Accessories - J")

    def test_item_then_group_default(self):
        ln = _line(expense_account="Stock Received But Not Billed - J")
        self.assertEqual(_resolve_line_head(ln, CLEAR, {}, {"X": "Lab Consumable - J"}, {"G": "Misc - J"}),
                         "Lab Consumable - J")
        self.assertEqual(_resolve_line_head(ln, CLEAR, {}, {}, {"G": "Misc - J"}), "Misc - J")

    def test_company_default_on_a_grn_line_yields_to_a_real_item_head(self):
        # ERPNext wrote "Cost of Goods Sold" on the GRN line because the item had
        # no head then; the item has one now.
        ln = _line(expense_account="Stock Received But Not Billed - J", grn_account="COGS - J")
        weak = {"COGS - J"}
        self.assertEqual(_resolve_line_head(ln, CLEAR, {}, {"X": "Stationery - J"}, {}, weak), "Stationery - J")
        self.assertEqual(_resolve_line_head(ln, CLEAR, {}, {}, {}, weak), "COGS - J")   # nothing better known

    def test_a_posted_line_account_is_never_overridden(self):
        # A direct invoice that POSTED to the company default keeps it.
        ln = _line(expense_account="COGS - J")
        self.assertEqual(_resolve_line_head(ln, CLEAR, {}, {"X": "Stationery - J"}, {}, {"COGS - J"}), "COGS - J")

    def test_nothing_known_keeps_the_posted_account(self):
        ln = _line(expense_account="Stock Received But Not Billed - J")
        self.assertEqual(_resolve_line_head(ln, CLEAR, {}, {}, {}), "Stock Received But Not Billed - J")


SUPPLIER = ("Supplier", "3C IT")


def _gl(account, debit=0, credit=0, party=("", "")):
    return {"account": account, "debit": debit, "credit": credit, "party_type": party[0], "party": party[1]}


class TestInvoiceMakeup(unittest.TestCase):

    def test_the_client_invoice(self):
        # Dr Asset RBNB 22,12,500 / Cr supplier — one head, nothing else.
        lines = [dict(_line(expense_account="Asset Received But Not Billed - J", amount=2212500),
                      head="Computer & Accessories - J")]
        gl = [_gl("Asset Received But Not Billed - J", debit=2212500),
              _gl("Sundry Creditors - J", credit=2212500, party=SUPPLIER)]
        heads, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER)
        self.assertEqual(heads, [("Computer & Accessories - J", 2212500)])
        self.assertEqual(parts, [("Computer & Accessories - J", 2212500)])

    def test_clearing_split_across_heads_and_gst_kept(self):
        # Two stock lines of different heads, one merged SRBNB row, GST on top.
        lines = [dict(_line(expense_account="Stock Received But Not Billed - J", amount=700), head="Stationery - J"),
                 dict(_line(expense_account="Stock Received But Not Billed - J", amount=300), head="Lab - J")]
        gl = [_gl("Stock Received But Not Billed - J", debit=1000), _gl("Input CGST - J", debit=90),
              _gl("Input SGST - J", debit=90), _gl("Creditors - J", credit=1180, party=SUPPLIER)]
        heads, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER)
        self.assertEqual([h for h, _ in heads], ["Stationery - J", "Lab - J"])
        self.assertEqual(dict(parts), {"Stationery - J": 700, "Lab - J": 300, "Input CGST - J": 90, "Input SGST - J": 90})
        self.assertEqual([a for a, _ in parts][:2], ["Stationery - J", "Lab - J"])   # heads first
        self.assertAlmostEqual(sum(v for _, v in parts), 1180)                          # ties to the bill

    def test_posted_clearing_amount_wins_over_line_amounts(self):
        # Invoice rate differs from the GRN's: the parts must still add to what was posted.
        lines = [dict(_line(expense_account="Stock Received But Not Billed - J", amount=333.33), head="A - J"),
                 dict(_line(expense_account="Stock Received But Not Billed - J", amount=666.67), head="B - J")]
        gl = [_gl("Stock Received But Not Billed - J", debit=1001), _gl("Creditors - J", credit=1001, party=SUPPLIER)]
        _, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER)
        self.assertAlmostEqual(sum(v for _, v in parts), 1001, places=2)

    def test_tds_is_a_credit_part_and_bank_leg_dropped(self):
        lines = [dict(_line(expense_account="Freight - J", amount=1000), head="Freight - J")]
        gl = [_gl("Freight - J", debit=1000), _gl("TDS Payable - J", credit=20),
              _gl("Creditors - J", credit=980, party=SUPPLIER),
              # paid on the spot: supplier debited, bank credited
              _gl("Creditors - J", debit=980, party=SUPPLIER), _gl("ICICI - J", credit=980)]
        heads, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER, [("ICICI - J", 980)])
        self.assertEqual(dict(parts), {"Freight - J": 1000, "TDS Payable - J": -20})

    def test_paid_from_an_overdraft_still_ties(self):
        # The bank is a LIABILITY here — an account-type rule would keep its leg.
        lines = [dict(_line(expense_account="Freight - J", amount=500), head="Freight - J")]
        gl = [_gl("Freight - J", debit=500), _gl("Creditors - J", credit=500, party=SUPPLIER),
              _gl("Creditors - J", debit=500, party=SUPPLIER), _gl("HDFC OD - J", credit=500)]
        _, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER, [("HDFC OD - J", 500)])
        self.assertEqual(parts, [("Freight - J", 500)])

    def test_write_off_is_not_part_of_the_bill(self):
        # Billed 1,003, the 3 written off: the bill row is still 1,003.
        lines = [dict(_line(expense_account="Freight - J", amount=1003), head="Freight - J")]
        gl = [_gl("Freight - J", debit=1003), _gl("Creditors - J", credit=1003, party=SUPPLIER),
              _gl("Creditors - J", debit=3, party=SUPPLIER), _gl("Write Off - J", credit=3)]
        _, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER, [("Write Off - J", 3)])
        self.assertEqual(parts, [("Freight - J", 1003)])

    def test_write_off_onto_a_head_the_bill_also_uses(self):
        # One GL row nets the bill's 50 against the 2 written off — only the 2 comes out.
        lines = [dict(_line(expense_account="Misc - J", amount=50), head="Misc - J")]
        gl = [_gl("Misc - J", debit=50, credit=2), _gl("Creditors - J", credit=50, party=SUPPLIER),
              _gl("Creditors - J", debit=2, party=SUPPLIER)]
        _, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER, [("Misc - J", 2)])
        self.assertEqual(parts, [("Misc - J", 50)])

    def test_debit_note_mirrors(self):
        lines = [dict(_line(expense_account="Stock Received But Not Billed - J", amount=-200), head="Lab - J")]
        gl = [_gl("Stock Received But Not Billed - J", credit=200), _gl("Creditors - J", debit=200, party=SUPPLIER)]
        heads, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER)
        self.assertEqual(heads, [("Lab - J", 200)])
        self.assertEqual(parts, [("Lab - J", -200)])

    def test_debit_note_refunded_on_the_spot(self):
        # A return's paid amount is negative: the bank was DEBITED, and still comes out.
        lines = [dict(_line(expense_account="Stock Received But Not Billed - J", amount=-200), head="Lab - J")]
        gl = [_gl("Stock Received But Not Billed - J", credit=200), _gl("Creditors - J", debit=200, party=SUPPLIER),
              _gl("Creditors - J", credit=200, party=SUPPLIER), _gl("ICICI - J", debit=200)]
        _, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER, [("ICICI - J", -200)])
        self.assertEqual(parts, [("Lab - J", -200)])

    def test_each_clearing_account_splits_over_its_own_heads(self):
        # Stock billed at 710 against a 700 GRN; the asset at 300. The stock
        # difference stays with the stock head and never leaks into the asset.
        lines = [dict(_line(expense_account="Stock Received But Not Billed - J", amount=700), head="Stationery - J"),
                 dict(_line(expense_account="Asset Received But Not Billed - J", amount=300), head="Computers - J")]
        gl = [_gl("Stock Received But Not Billed - J", debit=710), _gl("Asset Received But Not Billed - J", debit=300),
              _gl("Creditors - J", credit=1010, party=SUPPLIER)]
        _, parts = _invoice_makeup(gl, lines, CLEAR, SUPPLIER)
        self.assertEqual(dict(parts), {"Stationery - J": 710, "Computers - J": 300})


class TestLabels(unittest.TestCase):

    def test_single_and_several_heads(self):
        names = {"Computer & Accessories - J": "Computer & Accessories", "Lab - J": "Lab"}
        self.assertEqual(_heads_label([("Computer & Accessories - J", 1)], names), "Computer & Accessories")
        self.assertEqual(_heads_label([("Computer & Accessories - J", 9), ("Lab - J", 1), ("X - J", 1)], names),
                         "Computer & Accessories & 2 more")
        self.assertEqual(_heads_label([], names), "")

    def test_items_summary(self):
        self.assertEqual(_items_summary([{"name": "Interactive Flat Panel", "qty": 15, "amount": 2212500}]),
                         "Interactive Flat Panel × 15")
        self.assertEqual(_items_summary([{"name": "Pencil", "qty": 10, "amount": 50},
                                         {"name": "Cello Tape", "qty": 4, "amount": 400},
                                         {"name": "Stapler", "qty": 1, "amount": 90}]),
                         "Cello Tape × 4 & 2 more items")
        self.assertEqual(_items_summary([{"name": "Sand", "qty": 2.5, "amount": 1}, {"name": "Brick", "qty": 1, "amount": 0}]),
                         "Sand × 2.50 & 1 more item")
        self.assertEqual(_items_summary([]), "")
