"""Unit tests for the Dux Trial Balance (report/dux_trial_balance, its Excel export).

By Account resets Income and Expense opening at the fiscal-year boundary and
adds the prior-year result back as one computed "Accumulated Loss/Profit b/f"
row, so it ties. By Company and Account -> Party read the same reset slice
but never added it back: on a trust with prior-year P&L every company read
"out" by its own result while By Account tied. By Company now folds each
company's share into its own row; Account -> Party adds the computed row.

Ledger queries are mocked: these cover the arithmetic.
"""

import unittest
from unittest import mock

import frappe

from dux_voucher.dux_voucher.api import reports_export
from dux_voucher.dux_voucher.report.dux_trial_balance import dux_trial_balance as tb

F = ('{"company": ["College A"], "view": "By Account", '
     '"from_date": "2026-04-01", "to_date": "2027-03-31"}')
ENGINE = "dux_voucher.dux_voucher.report.dux_trial_balance.dux_trial_balance.execute"
RESET = "2026-04-01"


def _v(od=0.0, oc=0.0, d=0.0, c=0.0):
    """One slice entry: opening, period and closing on both sides."""
    return {"opening_debit": od, "opening_credit": oc, "debit": d, "credit": c,
            "closing_debit": od + d, "closing_credit": oc + c}


def _filters(view, **kw):
    f = frappe._dict(view=view, from_date="2026-04-01", to_date="2027-03-31",
                     show_net_values=1, show_group_accounts=1,
                     _pl_reset_date=RESET, _source="live")
    f.update(kw)
    return f


def _acc(name, account_name, account_type, root_type):
    return frappe._dict(name=name, account_name=account_name, account_type=account_type,
                        root_type=root_type, company="A")


def _total(rows):
    return next(r for r in rows if r.get("is_total"))


def _ties(total):
    return (abs(total["opening_debit"] - total["opening_credit"]) < 0.005
            and abs(total["closing_debit"] - total["closing_credit"]) < 0.005)


class TestByCompany(unittest.TestCase):
    """Each company carries its own prior-year result, so the view ties."""

    def _build(self, values, carry, **kw):
        with mock.patch.object(tb, "_slice", return_value=values), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_net",
                                  side_effect=lambda cos, f: carry.get(cos[0], 0.0)):
            return tb._build_by_company(_filters("By Company", **kw), list(carry) or ["A"])

    def _row(self, rows, company):
        return next(r for r in rows if r.get("company") == company)

    def test_each_company_nets_to_nil_when_its_books_tie(self):
        # A: a prior-year loss of 100 left its balance sheet 100 Cr once the
        # reset dropped it; B: a prior-year profit of 40 left B 40 Dr.
        rows = self._build({("A",): _v(oc=100, d=500, c=500), ("B",): _v(od=40, d=10, c=10)},
                           {"A": 100.0, "B": -40.0})
        for co in ("A", "B"):
            r = self._row(rows, co)
            for f in ("opening_debit", "opening_credit", "closing_debit", "closing_credit"):
                self.assertAlmostEqual(r[f], 0, msg=f"{co} {f}")
        a = self._row(rows, "A")
        self.assertEqual((a["debit"], a["credit"]), (500, 500))   # the period is untouched
        self.assertEqual(a["carry_forward"], 100.0)
        self.assertEqual(self._row(rows, "B")["carry_forward"], -40.0)
        self.assertTrue(_ties(_total(rows)))

    def test_a_company_whose_books_do_not_tie_shows_its_difference(self):
        rows = self._build({("A",): _v(oc=100, d=500, c=499)}, {"A": 100.0})
        a = self._row(rows, "A")
        self.assertAlmostEqual(a["closing_debit"], 1.0)
        self.assertAlmostEqual(a["closing_credit"], 0)

    def test_the_gross_view_adds_the_carry_on_its_own_side(self):
        rows = self._build({("A",): _v(oc=100, d=500, c=500)}, {"A": 100.0}, show_net_values=0)
        a = self._row(rows, "A")
        self.assertEqual((a["opening_debit"], a["opening_credit"]), (100, 100))
        self.assertEqual((a["closing_debit"], a["closing_credit"]), (600, 600))

    def test_nothing_is_added_when_the_reset_is_off(self):
        f = _filters("By Company", _pl_reset_date=None)
        self.assertEqual(tb._unclosed_pl_net(["A"], f), 0.0)
        with mock.patch.object(tb, "_slice", return_value={("A",): _v(od=5)}), \
                mock.patch.object(tb, "_company_currency", return_value="INR"):
            rows = tb._build_by_company(f, ["A"])
        a = self._row(rows, "A")
        self.assertNotIn("carry_forward", a)
        self.assertEqual((a["opening_debit"], a["closing_debit"]), (5, 5))

    def test_the_message_says_a_carry_forward_is_included(self):
        rows = self._build({("A",): _v(oc=100, d=500, c=500)}, {"A": 100.0})
        msg = tb._build_message(_filters("By Company"), ["A"], rows)
        self.assertIn("computed carry-forward", msg)
        self.assertIn("for this company", msg)
        msg = tb._build_message(_filters("By Company"), ["A", "B"], rows)
        self.assertIn("for these companies", msg)


class TestAccountParty(unittest.TestCase):
    """Account -> Party adds the carry-forward row, so it ties like By Account."""

    MASTER = [
        _acc("Debtors - A", "Debtors", "Receivable", "Asset"),
        _acc("Capital - A", "Capital", "", "Equity"),
        _acc("Salary - A", "Salary", "", "Expense"),
        _acc("Bank - A", "Bank", "Bank", "Asset"),
        _acc("Earnest Money - A", "Earnest Money", "", "Asset"),
    ]
    # Once the reset drops the prior-year loss of 100, the balance-sheet
    # opening nets 100 Cr: Debtors 100 Dr and Earnest Money 10 Dr against
    # Capital 210 Cr.
    VALUES = {
        ("Debtors - A", "Customer", "C1"): _v(od=70),
        ("Debtors - A", None, None): _v(od=30),
        ("Capital - A", None, None): _v(oc=210),
        ("Salary - A", None, None): _v(d=50),
        ("Bank - A", None, None): _v(c=50),
        ("Earnest Money - A", "Supplier", "S1"): _v(od=6),
        ("Earnest Money - A", None, None): _v(od=4),
    }

    def _build(self, **kw):
        with mock.patch.object(tb, "_slice", return_value=dict(self.VALUES)), \
                mock.patch.object(tb, "_account_master", return_value=self.MASTER), \
                mock.patch.object(tb, "_default_party_accounts", return_value={}), \
                mock.patch.object(tb, "_resolve_party_names", return_value={}), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=100.0):
            return tb._build_account_party(_filters("Account -> Party", **kw), ["A"])

    def test_the_view_ties_with_the_carry_forward_row(self):
        rows = self._build()
        carry = [r for r in rows if r.get("is_computed")]
        self.assertEqual(len(carry), 1)
        self.assertAlmostEqual(carry[0]["opening_debit"], 100)
        self.assertIsNone(carry[0]["parent_account"])
        self.assertTrue(_ties(_total(rows)))

    def test_control_accounts_only_adds_no_carry_row(self):
        rows = self._build(control_accounts_only=1)
        self.assertFalse([r for r in rows if r.get("is_computed")])
        top = {r["account"] for r in rows if not r.get("parent_account") and not r.get("is_total")}
        self.assertEqual(top, {"Debtors - A"})

    def _children(self, rows, account):
        return [r for r in rows if r.get("parent_account") == account]

    def test_a_plain_account_with_no_party_has_no_unattributed_row(self):
        rows = self._build()
        for account in ("Capital - A", "Salary - A", "Bank - A"):
            self.assertEqual(self._children(rows, account), [], account)
        top = {r["account"] for r in rows if not r.get("parent_account")}
        self.assertTrue({"Capital - A", "Salary - A", "Bank - A"} <= top)
        self.assertTrue(_ties(_total(rows)))

    def test_a_control_account_keeps_its_unattributed_row(self):
        deb = self._children(self._build(), "Debtors - A")
        self.assertEqual(sorted(bool(r.get("is_unattributed")) for r in deb), [False, True])

    def test_a_plain_account_that_carries_parties_still_opens(self):
        em = self._children(self._build(), "Earnest Money - A")
        self.assertEqual(sorted(bool(r.get("is_unattributed")) for r in em), [False, True])

    def test_the_students_ledger_counts_as_a_control_account(self):
        # Blank account_type, but it carries one Student per line.
        master = self.MASTER + [_acc("Admission/Registration Fee (Provisional) - A",
                                     "Admission/Registration Fee (Provisional)", "", "Liability")]
        values = dict(self.VALUES)
        values[("Admission/Registration Fee (Provisional) - A", None, None)] = _v(oc=5)
        values[("Capital - A", None, None)] = _v(oc=205)
        with mock.patch.object(tb, "_slice", return_value=values), \
                mock.patch.object(tb, "_account_master", return_value=master), \
                mock.patch.object(tb, "_default_party_accounts", return_value={}), \
                mock.patch.object(tb, "_resolve_party_names", return_value={}), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=100.0):
            rows = tb._build_account_party(_filters("Account -> Party"), ["A"])
        kids = self._children(rows, "Admission/Registration Fee (Provisional) - A")
        self.assertEqual([bool(r.get("is_unattributed")) for r in kids], [True])


class TestByPartyNet(unittest.TestCase):
    """Most of a ledger has no party, so By Party's total reads as a net."""

    def _data(self, dr, cr):
        return [{"party": "C1", "closing_debit": dr, "closing_credit": cr},
                {"is_total": 1, "opening_debit": 0, "opening_credit": 0, "debit": 0,
                 "credit": 0, "closing_debit": dr, "closing_credit": cr}]

    def test_the_message_gives_the_net_not_a_difference(self):
        msg = tb._build_message(_filters("By Party"), ["A"], self._data(9300300.0, 0.0))
        self.assertIn("net of parties", msg)
        self.assertIn("Dr", msg)
        self.assertNotIn("out of balance", msg)
        self.assertIn("Cr", tb._build_message(_filters("By Party"), ["A"], self._data(0.0, 5.0)))

    def test_the_summary_card_is_a_net_and_not_red(self):
        s = tb._summary(self._data(9300300.0, 0.0), _filters("By Party"))
        self.assertEqual((s[-1]["label"], s[-1]["indicator"]), ("Net of parties", "blue"))

    def test_by_account_still_reports_a_difference(self):
        msg = tb._build_message(_filters("By Account"), ["A"], self._data(10.0, 0.0))
        self.assertIn("out of balance", msg)
        s = tb._summary(self._data(10.0, 0.0), _filters("By Account"))
        self.assertEqual((s[-1]["label"], s[-1]["indicator"]), ("Difference", "red"))

    def test_the_excel_title_block_says_net_of_all_parties(self):
        import io
        from openpyxl import load_workbook
        rows = self._data(9300300.0, 0.0)
        rows[0].update(opening_debit=0, opening_credit=0, debit=0, credit=0)
        f = F.replace('"By Account"', '"By Party"')
        with mock.patch("frappe.desk.query_report.get_report_doc"), \
                mock.patch(ENGINE, return_value=([{"label": "Party"}], rows, "", None, None)):
            reports_export.export_trial_balance_xlsx(filters=f)
        a3 = load_workbook(io.BytesIO(frappe.local.response.filecontent)).active["A3"].value
        self.assertTrue(a3.startswith("Net of all parties:"), a3)
        self.assertTrue(a3.endswith(" Dr"), a3)


class TestNarrowingFilters(unittest.TestCase):
    """Cost Center / Project are read from the live ledger, carry included.

    The monthly aggregate has no cost centre or project, and a trust (more
    companies than the live threshold) was served from it with the filter
    simply dropped: the report came back as the trust's whole ledger."""

    TRUST = [f"College {i}" for i in range(7)]
    AGG = "dux_voucher.dux_voucher.api.tb_aggregate"

    def _slice(self, **kw):
        f = _filters("By Account", **kw)
        with mock.patch(f"{self.AGG}.can_serve", return_value=True), \
                mock.patch(f"{self.AGG}.built_at", return_value="2026-11-19 00:02"), \
                mock.patch(f"{self.AGG}.fetch", return_value={"agg": 1}) as fetch, \
                mock.patch.object(tb, "_slice_live", return_value={"live": 1}) as live:
            out = tb._slice(self.TRUST, ("account",), f)
        return f, out, fetch, live

    def test_a_trust_under_a_cost_center_filter_reads_live(self):
        f, out, fetch, live = self._slice(cost_center=["Main - A"])
        fetch.assert_not_called()
        live.assert_called_once()
        self.assertEqual((out, f._source), ({"live": 1}, "live"))
        self.assertIn("Cost Center", f._source_note)

    def test_a_trust_under_a_project_filter_reads_live(self):
        f, out, fetch, _live = self._slice(project=["New Hostel"])
        fetch.assert_not_called()
        self.assertEqual(f._source, "live")
        self.assertIn("Project", f._source_note)

    def test_without_them_a_trust_still_reads_the_aggregate(self):
        f, out, fetch, live = self._slice()
        fetch.assert_called_once()
        live.assert_not_called()
        self.assertEqual((out, f._source), ({"agg": 1}, "aggregate"))
        self.assertFalse(f.get("_source_note"))

    def test_the_carry_forward_is_taken_from_the_same_slice(self):
        f = _filters("By Account", cost_center=["Main - A"], project="New Hostel")
        with mock.patch.object(tb, "_touched_companies", side_effect=lambda cos, _f: list(cos)), \
                mock.patch.object(frappe.db, "sql",
                                  return_value=[frappe._dict(debit=10.0, credit=4.0)]) as sql:
            self.assertEqual(tb._unclosed_pl_net(["A"], f), 6.0)
        query, params = sql.call_args[0][:2]
        self.assertIn("gle.cost_center IN %(cost_center)s", query)
        self.assertIn("gle.project IN %(project)s", query)
        self.assertEqual(params["cost_center"], ("Main - A",))
        self.assertEqual(params["project"], ("New Hostel",))

    def test_only_the_companies_that_carry_the_project_are_queried(self):
        # GL Entry has no index on project: every company queried is a scan
        # of its whole ledger, so the ones without the project are skipped.
        f = _filters("By Account", project=["New Hostel"])
        with mock.patch.object(frappe.db, "sql_list", return_value=["College 2"]) as lookup, \
                mock.patch.object(tb, "_gl_aggregate_one", return_value=[]) as one:
            tb._gl_aggregate(self.TRUST, ("account",), f, opening=False)
            self.assertEqual([c.args[0] for c in one.call_args_list], ["College 2"])
            # Known per company for the rest of the request, dates or not.
            self.assertEqual(tb._touched_companies(["College 3", "College 2"], f), ["College 2"])
        lookup.assert_called_once()
        self.assertIn("gle.project IN %(project)s", lookup.call_args[0][0])

    def test_without_a_narrowing_filter_nothing_is_looked_up(self):
        f = _filters("By Account")
        with mock.patch.object(frappe.db, "sql_list") as lookup:
            self.assertEqual(tb._touched_companies(self.TRUST, f), self.TRUST)
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
