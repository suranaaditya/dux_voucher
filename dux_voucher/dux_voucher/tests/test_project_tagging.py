"""Unit tests for Set Project on Purchase Order (api/project_tagging.py).

Covers the pure parts that decide what is written:

* reading a site team's sheet by its headers, wherever they sit;
* pairing posted ledger rows with the rows ERPNext would post now, which
  is the only way a MIXED invoice's ledger may be retagged — anything but a
  clean one-to-one pairing must refuse.

The end-to-end walk (PO → GRN → invoice → payment, mixed documents, closed
periods, conflicts, overwrite) posts real documents and runs as the
scenario on the dev site, as the other module tests here do.
"""

import unittest

import frappe

from dux_voucher.dux_voucher.api.project_tagging import (
    detect_columns,
    match_ledger,
    parse_table,
)


class TestSheet(unittest.TestCase):

    def test_site_team_layout(self):
        cols = detect_columns(["NO.", "COMPANY ", "PO Number", "Vendor Name", "PO AMOUNT ", "PROJECT NAME"])
        self.assertEqual(cols, {"po": 2, "supplier": 3, "amount": 4, "project": 5})

    def test_po_amount_is_not_the_po_column(self):
        self.assertEqual(detect_columns(["PO Amount", "Purchase Order", "Project"])["po"], 1)

    def test_title_row_above_header_and_blank_lines(self):
        out = parse_table([
            ["PO's without Project Name"],
            [],
            ["PO No", "Project"],
            ["GHREMF/PUNE/PO/26-27/00218", "GHREMFP - New Workshop Building"],
            ["", ""],
            [" PUR-ORD-2026-00017 ", "PROJ-0001"],
        ])
        self.assertEqual(out["header_row"], 3)
        self.assertEqual([r["purchase_order"] for r in out["rows"]],
                         ["GHREMF/PUNE/PO/26-27/00218", "PUR-ORD-2026-00017"])
        self.assertEqual(out["rows"][0]["line"], 4)

    def test_amount_with_commas(self):
        out = parse_table([["PO Number", "PO Amount", "Project"], ["X", "1,21,787.80", "P"]])
        self.assertEqual(out["rows"][0]["amount"], 121787.8)

    def test_no_header_refuses(self):
        with self.assertRaises(frappe.ValidationError):
            parse_table([["Supplier", "Amount"], ["A", 1]])


def _gl(name, account, debit=0, credit=0, party="", cost_center="Main"):
    return {"name": name, "account": account, "party_type": "Supplier" if party else "",
            "party": party, "cost_center": cost_center, "debit": debit, "credit": credit}


def _exp(account, project, debit=0, credit=0, party="", cost_center="Main"):
    r = _gl(None, account, debit, credit, party, cost_center)
    r["project"] = project
    return r


class TestLedgerMatch(unittest.TestCase):

    def test_mixed_invoice_pairs_line_by_line(self):
        existing = [_gl("g1", "Creditors", credit=300, party="S"),
                    _gl("g2", "CWIP", debit=100), _gl("g3", "Steel", debit=200)]
        expected = [_exp("Creditors", "", credit=300, party="S"),
                    _exp("CWIP", "P1", debit=100), _exp("Steel", "", debit=200)]
        self.assertEqual(match_ledger(existing, expected), {"g1": "", "g2": "P1", "g3": ""})

    def test_a_merged_row_that_would_now_split_refuses(self):
        # Two lines on one account were posted as ONE merged row; tagged
        # differently they would be two rows — cannot be fixed in place.
        existing = [_gl("g1", "Creditors", credit=300, party="S"), _gl("g2", "CWIP", debit=300)]
        expected = [_exp("Creditors", "", credit=300, party="S"),
                    _exp("CWIP", "P1", debit=100), _exp("CWIP", "", debit=200)]
        self.assertIsNone(match_ledger(existing, expected))

    def test_any_amount_difference_refuses(self):
        existing = [_gl("g1", "CWIP", debit=100.0), _gl("g2", "Creditors", credit=100, party="S")]
        expected = [_exp("CWIP", "P1", debit=100.4), _exp("Creditors", "", credit=100.4, party="S")]
        self.assertIsNone(match_ledger(existing, expected))

    def test_round_off_row_takes_the_header_project(self):
        existing = [_gl("g1", "CWIP", debit=100), _gl("g2", "Creditors", credit=100.5, party="S"),
                    _gl("g3", "Round Off", debit=0.5)]
        expected = [_exp("CWIP", "P1", debit=100), _exp("Creditors", "P1", credit=100.5, party="S")]
        self.assertEqual(match_ledger(existing, expected, "Round Off", "P1"),
                         {"g1": "P1", "g2": "P1", "g3": "P1"})

    def test_extra_expected_row_refuses(self):
        existing = [_gl("g1", "CWIP", debit=100)]
        expected = [_exp("CWIP", "P1", debit=100), _exp("Tax", "P1", debit=18)]
        self.assertIsNone(match_ledger(existing, expected))

    def test_equal_rows_keep_their_own_project(self):
        # Two identical posted rows, one already on Q. The tagged line must not
        # take Q's row and hand Q the blank one.
        existing = [dict(_gl("g1", "CWIP", debit=100), project=""),
                    dict(_gl("g2", "CWIP", debit=100), project="Q")]
        expected = [_exp("CWIP", "P", debit=100), _exp("CWIP", "Q", debit=100)]
        self.assertEqual(match_ledger(existing, expected), {"g1": "P", "g2": "Q"})

    def test_zero_expected_rows_are_ignored(self):
        existing = [_gl("g1", "CWIP", debit=100)]
        expected = [_exp("CWIP", "P1", debit=100), _exp("Tax", "P1")]
        self.assertEqual(match_ledger(existing, expected), {"g1": "P1"})
