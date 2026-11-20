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

    def test_a_company_with_nothing_this_period_still_carries_last_years_result(self):
        # Under a Cost Center filter A has no line this period and nothing in its
        # opening once the reset drops last year's expense, yet that cost centre
        # booked 500 of it. By Account counts the 500, so this view must too.
        rows = self._build({("B",): _v(od=40, d=10, c=10)}, {"A": 500.0, "B": -40.0, "C": 0.0})
        a = self._row(rows, "A")
        self.assertEqual((a["opening_debit"], a["closing_debit"]), (500.0, 500.0))
        self.assertEqual(a["carry_forward"], 500.0)
        self.assertFalse([r for r in rows if r.get("company") == "C"])   # nothing at all: no row
        t = _total(rows)
        self.assertAlmostEqual(t["closing_debit"] - t["closing_credit"], 500.0)

    def test_the_excel_says_the_carry_is_inside_the_company_figures(self):
        import io
        from openpyxl import load_workbook
        rows = self._build({("A",): _v(oc=100, d=500, c=500)}, {"A": 100.0})
        f = F.replace('"By Account"', '"By Company"')
        cols = tb._columns_for(frappe._dict(view="By Company"), ["A"])
        with mock.patch("frappe.desk.query_report.get_report_doc"), \
                mock.patch(ENGINE, return_value=(cols, rows, "", None, None)):
            reports_export.export_trial_balance_xlsx(filters=f)
        ws = load_workbook(io.BytesIO(frappe.local.response.filecontent)).active
        self.assertIn("prior-year", ws["A4"].value or "")
        # no carry, no note
        plain = self._build({("A",): _v(od=5, oc=5)}, {"A": 0.0})
        with mock.patch("frappe.desk.query_report.get_report_doc"), \
                mock.patch(ENGINE, return_value=(cols, plain, "", None, None)):
            reports_export.export_trial_balance_xlsx(filters=f)
        ws = load_workbook(io.BytesIO(frappe.local.response.filecontent)).active
        self.assertIsNone(ws["A4"].value)

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

    def test_an_empty_slice_still_shows_last_years_carry(self):
        # A Project seen only on last year's expense lines: nothing in the
        # period or the opening, yet By Account shows a carry of 100.
        with mock.patch.object(tb, "_slice", return_value={}), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=100.0):
            rows = tb._build_account_party(_filters("Account -> Party"), ["A"])
            only_ctl = tb._build_account_party(
                _filters("Account -> Party", control_accounts_only=1), ["A"])
        self.assertEqual([bool(r.get("is_computed")) for r in rows], [True, False])
        t = _total(rows)
        self.assertAlmostEqual(t["closing_debit"] - t["closing_credit"], 100.0)
        self.assertEqual(only_ctl, [])

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

    def test_the_excel_names_its_party_column_party(self):
        # The engine's own By Party columns start with Party Type, but column A
        # holds the party's name.
        import io
        from openpyxl import load_workbook
        rows = self._data(10.0, 0.0)
        rows[0].update(party_name="Party One", opening_debit=0, opening_credit=0, debit=0, credit=0)
        f = F.replace('"By Account"', '"By Party"')
        cols = tb._columns_for(frappe._dict(view="By Party"), ["A"])
        self.assertEqual(cols[0]["label"], "Party Type")
        with mock.patch("frappe.desk.query_report.get_report_doc"), \
                mock.patch(ENGINE, return_value=(cols, rows, "", None, None)):
            reports_export.export_trial_balance_xlsx(filters=f)
        ws = load_workbook(io.BytesIO(frappe.local.response.filecontent)).active
        self.assertEqual((ws["A5"].value, ws["A6"].value), ("Party", "Party One"))


class TestPeriodComparison(unittest.TestCase):
    """Each range of a comparison resets income and expense at its own year.

    On a trust (aggregate tier) last year's column read the whole prior-year
    carry of THIS year on top of its own figures: 4,85,97,38,658.42 where the
    ledger itself gave 36,612.67 in testing."""

    def test_the_earlier_range_resets_at_its_own_fiscal_year(self):
        f = frappe._dict(view="By Account", compare="Period", fiscal_year="2026-2027",
                         from_date=frappe.utils.getdate("2026-04-01"),
                         to_date=frappe.utils.getdate("2026-10-31"),
                         compare_from="2025-04-01", compare_to="2025-10-31",
                         show_group_accounts=1)
        seen = []

        def build(sub, cos):
            seen.append(sub)
            return []

        reset = lambda sub: sub.get("fiscal_year") or str(sub.from_date)  # noqa: E731
        with mock.patch.object(tb, "_build_by_account", side_effect=build), \
                mock.patch.object(tb, "_pl_reset_date", side_effect=reset):
            tb._build_comparison(f, ["A", "B"])
        self.assertEqual([s._pl_reset_date for s in seen], ["2026-2027", "2025-04-01"])
        self.assertEqual(f.fiscal_year, "2026-2027")   # the caller's filters are untouched

    def test_the_aggregate_carry_has_the_live_bounds(self):
        from dux_voucher.dux_voucher.api import tb_aggregate
        with mock.patch.object(frappe.db, "sql", return_value=[frappe._dict(net=5.0)]) as sql:
            net = tb_aggregate.unclosed_pl(["A"], "2025-04-01", "2025-10-31", "2026-04-01")
        self.assertEqual(net, 5.0)
        query, params = sql.call_args[0][:2]
        self.assertEqual((params["from_p"], params["to_p"], params["pl_p"]),
                         ("2025-04", "2025-10", "2026-04"))
        self.assertIn("agg.period < %(from_p)s", query)
        self.assertIn("agg.period <= %(to_p)s", query)


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


# ── several companies: merged charts, company columns ─────────────────

def _master(*specs):
    """Account master rows: (name, company, account_name, parent, root_type,
    is_group[, account_type])."""
    out = []
    for i, sp in enumerate(specs):
        name, co, acc_name, parent, root, grp = sp[:6]
        out.append(frappe._dict(
            name=name, company=co, account_name=acc_name, account_number=None,
            parent_account=parent, root_type=root, report_type="Balance Sheet",
            account_type=sp[6] if len(sp) > 6 else "", is_group=grp, lft=i + 1, rgt=i + 2))
    return out


def _signed(vals, stage):
    """Dr less Cr of one stage ("opening" / "closing") of a six-value list."""
    i = 0 if stage == "opening" else 4
    return vals[i] - vals[i + 1]


class TestMergedChart(unittest.TestCase):
    """The colleges' charts were cloned and then drifted. Merged on name alone,
    a row followed whichever college was read last: one college filing
    Temporary Opening under Equity carried every college's into Source of
    Funds. An account a college files under another parent is now a row of its
    own there, and one that is a group in one college and a ledger in another
    is two rows."""

    # A files Cash under Assets; B under Bank, a group under Assets.
    MASTER = _master(
        ("Assets - A", "A", "Assets", None, "Asset", 1),
        ("Cash - A", "A", "Cash", "Assets - A", "Asset", 0),
        ("Bank - A", "A", "Bank", "Assets - A", "Asset", 1),
        ("Liabilities - A", "A", "Liabilities", None, "Liability", 1),
        ("Capital - A", "A", "Capital", "Liabilities - A", "Liability", 0),
        ("Assets - B", "B", "Assets", None, "Asset", 1),
        ("Bank - B", "B", "Bank", "Assets - B", "Asset", 1),
        ("Cash - B", "B", "Cash", "Bank - B", "Asset", 0),
        ("Liabilities - B", "B", "Liabilities", None, "Liability", 1),
        ("Capital - B", "B", "Capital", "Liabilities - B", "Liability", 0),
    )
    VALUES = {("Cash - A",): _v(od=100), ("Capital - A",): _v(oc=100),
              ("Cash - B",): _v(od=40), ("Capital - B",): _v(oc=40)}

    def _build(self, master=None, values=None, companies=("A", "B"), **kw):
        with mock.patch.object(tb, "_slice", return_value=dict(values or self.VALUES)), \
                mock.patch.object(tb, "_account_master", return_value=master or self.MASTER), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=0.0):
            return tb._build_by_account(_filters("By Account", **kw), list(companies))

    def test_an_account_filed_under_another_parent_is_its_own_row(self):
        rows = self._build()
        by = {r["account"]: r for r in rows if not r.get("is_total")}
        split = "cash" + tb.KEY_SEP + "bank"
        self.assertEqual((by["cash"]["parent_account"], by["cash"]["closing_debit"]), ("assets", 100))
        self.assertEqual((by[split]["parent_account"], by[split]["closing_debit"]), ("bank", 40))
        self.assertEqual(by[split]["account_name"], "Cash (under Bank)")
        # every group is the sum of the rows under it
        self.assertEqual(by["bank"]["closing_debit"], 40)
        self.assertEqual(by["assets"]["closing_debit"], 140)
        self.assertTrue(_ties(_total(rows)))
        flat = self._build(show_group_accounts=0)
        self.assertEqual(sorted(r["account_name"] for r in flat if not r.get("is_total")),
                         ["Capital", "Cash", "Cash (under Bank)"])
        self.assertTrue(_ties(_total(flat)))

    def test_the_placement_most_companies_share_keeps_the_plain_row(self):
        master = _master(
            ("Assets - A", "A", "Assets", None, "Asset", 1),
            ("Cash - A", "A", "Cash", "Assets - A", "Asset", 0),
            ("Assets - B", "B", "Assets", None, "Asset", 1),
            ("Cash - B", "B", "Cash", "Assets - B", "Asset", 0),
            ("Assets - C", "C", "Assets", None, "Asset", 1),
            ("Bank - C", "C", "Bank", "Assets - C", "Asset", 1),
            ("Cash - C", "C", "Cash", "Bank - C", "Asset", 0),
        )
        keys, apart = tb._merge_keys(master, ["C", "A", "B"])   # C listed first, still outvoted
        self.assertEqual((keys["Cash - A"], keys["Cash - B"]), ("cash", "cash"))
        self.assertEqual(keys["Cash - C"], "cash" + tb.KEY_SEP + "bank")
        self.assertEqual(apart, {"cash" + tb.KEY_SEP + "bank": "bank"})
        # one each: the company listed first keeps the plain row
        keys, _apart = tb._merge_keys(self.MASTER, ["B", "A"])
        self.assertEqual((keys["Cash - B"], keys["Cash - A"]), ("cash", "cash" + tb.KEY_SEP + "assets"))

    def test_a_group_in_one_college_and_a_ledger_in_another_are_two_rows(self):
        master = _master(
            ("Liabilities - A", "A", "Liabilities", None, "Liability", 1),
            ("Loans - A", "A", "Loans", "Liabilities - A", "Liability", 1),
            ("Term Loan - A", "A", "Term Loan", "Loans - A", "Liability", 0),
            ("Assets - A", "A", "Assets", None, "Asset", 1),
            ("Cash - A", "A", "Cash", "Assets - A", "Asset", 0),
            ("Liabilities - B", "B", "Liabilities", None, "Liability", 1),
            ("Loans - B", "B", "Loans", "Liabilities - B", "Liability", 0),
            ("Assets - B", "B", "Assets", None, "Asset", 1),
            ("Cash - B", "B", "Cash", "Assets - B", "Asset", 0),
        )
        values = {("Term Loan - A",): _v(oc=70), ("Cash - A",): _v(od=70),
                  ("Loans - B",): _v(oc=30), ("Cash - B",): _v(od=30)}
        # Merged, hiding group accounts either dropped B's loan with A's group,
        # or kept it as a ledger holding A's term loan as well: out either way.
        flat = self._build(master, values, show_group_accounts=0)
        self.assertTrue(_ties(_total(flat)))
        loans = [r for r in flat if r["account_name"] == "Loans"]
        self.assertEqual([r["closing_credit"] for r in loans], [30])
        self.assertIn("Term Loan", [r["account_name"] for r in flat])
        tree = self._build(master, values)
        self.assertTrue(_ties(_total(tree)))
        by = {r["account"]: r for r in tree if not r.get("is_total")}
        self.assertEqual(by["loans"]["is_group_account"], 0)
        self.assertEqual(by["loans" + tb.GROUP_SUFFIX]["is_group_account"], 1)
        self.assertEqual(by["liabilities"]["closing_credit"], 100)

    def test_a_single_company_keeps_its_own_names(self):
        rows = self._build(companies=("A",))
        self.assertIn("Cash - A", [r["account"] for r in rows])


if __name__ == "__main__":
    unittest.main()
