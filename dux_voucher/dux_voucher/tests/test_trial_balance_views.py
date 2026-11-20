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


class TestCompanyColumns(unittest.TestCase):
    """Each company's own figure beside the consolidated one.

    Two colleges, A and B, each with a Cash, Debtors and Capital account, so
    every account merges across the two. A's cash is 130 Dr; B's is a 40 Cr
    overdraft; both sets of books tie on their own."""

    MASTER = _master(
        ("Assets - A", "A", "Assets", None, "Asset", 1),
        ("Cash - A", "A", "Cash", "Assets - A", "Asset", 0),
        ("Debtors - A", "A", "Debtors", "Assets - A", "Asset", 0, "Receivable"),
        ("Liabilities - A", "A", "Liabilities", None, "Liability", 1),
        ("Capital - A", "A", "Capital", "Liabilities - A", "Liability", 0),
        ("Assets - B", "B", "Assets", None, "Asset", 1),
        ("Cash - B", "B", "Cash", "Assets - B", "Asset", 0),
        ("Debtors - B", "B", "Debtors", "Assets - B", "Asset", 0, "Receivable"),
        ("Liabilities - B", "B", "Liabilities", None, "Liability", 1),
        ("Capital - B", "B", "Capital", "Liabilities - B", "Liability", 0),
    )
    VALUES = {
        ("Cash - A",): _v(od=100, d=50, c=20),
        ("Debtors - A",): _v(od=30),
        ("Capital - A",): _v(oc=130, d=20, c=50),
        ("Cash - B",): _v(oc=40),
        ("Debtors - B",): _v(od=10),
        ("Capital - B",): _v(od=30),
    }

    def _build(self, values=None, shares=None, companies=("A", "B"), **kw):
        kw.setdefault("company_columns", 1)
        f = _filters("By Account", **kw)
        with mock.patch.object(tb, "_slice", return_value=dict(values or self.VALUES)), \
                mock.patch.object(tb, "_account_master", return_value=self.MASTER), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_shares", return_value=dict(shares or {})), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=0.0):
            return tb._build_by_account(f, list(companies)), f

    def _row(self, rows, key):
        return next(r for r in rows if r.get("account") == key)

    def test_each_company_keeps_its_own_figure_on_the_merged_row(self):
        rows, f = self._build()
        self.assertTrue(f._company_columns)
        cash = self._row(rows, "cash")
        self.assertEqual(cash["cv"], [[100, 0, 50, 20, 130, 0], [0, 40, 0, 0, 0, 40]])
        # consolidated: 100 Dr and 40 Cr open at 60 Dr, as today
        self.assertEqual((cash["opening_debit"], cash["closing_debit"]), (60, 90))

    def test_the_columns_add_up_to_the_consolidated_figure(self):
        for net in (0, 1):
            rows, _f = self._build(show_net_values=net)
            for r in rows:
                if not r.get("cv"):
                    continue
                cv = [c or [0.0] * 6 for c in r["cv"]]
                own = [r[k] for k in tb.VALUE_FIELDS]
                if net:
                    # netted per company: the signed figure adds up, and the
                    # period is untouched
                    for stage in ("opening", "closing"):
                        self.assertAlmostEqual(sum(_signed(c, stage) for c in cv),
                                               _signed(own, stage), msg=r["account"])
                    for i in (2, 3):
                        self.assertAlmostEqual(sum(c[i] for c in cv), own[i], msg=r["account"])
                else:
                    for i in range(6):
                        self.assertAlmostEqual(sum(c[i] for c in cv), own[i], msg=r["account"])

    def test_groups_roll_up_company_by_company(self):
        rows, _f = self._build()
        assets = self._row(rows, "assets")
        self.assertEqual(assets["cv"], [[130, 0, 50, 20, 160, 0], [0, 30, 0, 0, 0, 30]])

    def test_each_companys_total_is_its_own_difference(self):
        rows, _f = self._build()
        a, b = _total(rows)["cv"]
        for c in (a, b):   # both sets of books tie
            self.assertAlmostEqual(_signed(c, "opening"), 0)
            self.assertAlmostEqual(_signed(c, "closing"), 0)
        self.assertEqual((a[2], a[3]), (70, 70))
        # Without group rows the leaves are netted one by one, so the gross
        # totals differ, but each company still comes to its own difference.
        flat, _f = self._build(show_group_accounts=0)
        for c, g in zip(_total(flat)["cv"], _total(rows)["cv"]):
            for stage in ("opening", "closing"):
                self.assertAlmostEqual(_signed(c, stage), _signed(g, stage))
            self.assertEqual((c[2], c[3]), (g[2], g[3]))

    def test_a_row_that_nets_to_nil_across_companies_is_still_shown(self):
        values = dict(self.VALUES)
        values[("Debtors - A",)] = _v(od=30)
        values[("Debtors - B",)] = _v(oc=30)
        values[("Capital - B",)] = _v(od=70)
        rows, _f = self._build(values)
        deb = self._row(rows, "debtors")
        self.assertEqual((deb["opening_debit"], deb["opening_credit"]), (0, 0))
        self.assertEqual(deb["cv"], [[30, 0, 0, 0, 30, 0], [0, 30, 0, 0, 0, 30]])
        # without company columns there is nothing to show
        with mock.patch.object(tb, "_slice", return_value=values), \
                mock.patch.object(tb, "_account_master", return_value=self.MASTER), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=0.0):
            plain = tb._build_by_account(_filters("By Account"), ["A", "B"])
        self.assertFalse([r for r in plain if r.get("account") == "debtors"])
        self.assertFalse([r for r in plain if r.get("cv")])

    def test_a_company_without_the_account_has_no_figure(self):
        values = {k: v for k, v in self.VALUES.items() if k != ("Debtors - B",)}
        values[("Capital - B",)] = _v(od=40)
        rows, _f = self._build(values)
        self.assertIsNone(self._row(rows, "debtors")["cv"][1])

    def test_control_rows_say_which_company_each_account_is(self):
        rows, _f = self._build()
        deb = self._row(rows, "debtors")
        self.assertEqual(deb["members"], ["Debtors - A", "Debtors - B"])
        self.assertEqual(deb["member_companies"], ["A", "B"])
        # Combined too: a party drill needs to know the row spans two companies.
        plain, _f = self._build(company_columns=0)
        self.assertEqual(self._row(plain, "debtors")["member_companies"], ["A", "B"])

    def test_the_carry_is_split_by_company(self):
        # A's books ran a prior-year loss of 100, B's a profit of 40.
        values = dict(self.VALUES)
        values[("Capital - A",)] = _v(oc=230, d=20, c=50)
        values[("Capital - B",)] = _v(od=70)
        rows, _f = self._build(values, shares={"A": 100.0, "B": -40.0})
        carry = next(r for r in rows if r.get("is_computed"))
        self.assertEqual((carry["opening_debit"], carry["closing_debit"]), (60, 60))
        self.assertEqual(carry["cv"], [[100, 0, 0, 0, 100, 0], [0, 40, 0, 0, 0, 40]])
        # A loss in one college and a profit in the other: "Accumulated Loss"
        # over B's Cr column would be wrong for B.
        self.assertIn("Profit / Loss", carry["account_name"])
        a, b = _total(rows)["cv"]
        for c in (a, b):
            self.assertAlmostEqual(_signed(c, "closing"), 0)
        self.assertTrue(_ties(_total(rows)))

    def test_a_carry_of_one_sign_keeps_its_name(self):
        values = dict(self.VALUES)
        values[("Capital - A",)] = _v(oc=230, d=20, c=50)
        values[("Capital - B",)] = _v(oc=10)
        rows, _f = self._build(values, shares={"A": 100.0, "B": 40.0})
        carry = next(r for r in rows if r.get("is_computed"))
        self.assertTrue(carry["account_name"].startswith("Accumulated Loss"))
        self.assertEqual(carry["closing_debit"], 140)

    def test_shares_that_cancel_still_show_in_their_columns(self):
        values = dict(self.VALUES)
        values[("Capital - A",)] = _v(oc=180, d=20, c=50)
        values[("Capital - B",)] = _v(od=80)
        rows, _f = self._build(values, shares={"A": 50.0, "B": -50.0})
        carry = next(r for r in rows if r.get("is_computed"))
        self.assertEqual([carry[k] for k in tb.VALUE_FIELDS], [0, 0, 0, 0, 0, 0])
        self.assertEqual(carry["cv"], [[50, 0, 0, 0, 50, 0], [0, 50, 0, 0, 0, 50]])
        self.assertIn("Profit / Loss", carry["account_name"])
        for c in _total(rows)["cv"]:   # each college still ties with its own share
            self.assertAlmostEqual(_signed(c, "closing"), 0)
        self.assertFalse([r for r in self._build()[0] if r.get("is_computed")])   # no shares

    def test_each_company_rolls_up_as_its_own_chart_does(self):
        # A files Cash under Assets, B under Bank: each column's groups are that
        # company's own subtotals.
        t = TestMergedChart
        with mock.patch.object(tb, "_slice", return_value=dict(t.VALUES)), \
                mock.patch.object(tb, "_account_master", return_value=t.MASTER), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_shares", return_value={}), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=0.0):
            rows = tb._build_by_account(_filters("By Account", company_columns=1), ["A", "B"])
        cv = {r["account"]: r["cv"] for r in rows if not r.get("is_total")}
        self.assertEqual(cv["assets"], [[100, 0, 0, 0, 100, 0], [40, 0, 0, 0, 40, 0]])
        self.assertEqual(cv["bank"], [None, [40, 0, 0, 0, 40, 0]])
        self.assertEqual(cv["cash"], [[100, 0, 0, 0, 100, 0], None])
        self.assertEqual(cv["cash" + tb.KEY_SEP + "bank"], [None, [40, 0, 0, 0, 40, 0]])

    def test_only_two_or_more_companies_on_a_shared_view(self):
        on = frappe._dict(company_columns=1, view="By Account")
        self.assertTrue(tb._company_columns(on, ["A", "B"]))
        self.assertTrue(tb._company_columns(frappe._dict(on, view="By Party"), ["A", "B"]))
        self.assertFalse(tb._company_columns(on, ["A"]))
        self.assertFalse(tb._company_columns(frappe._dict(on, view="By Company"), ["A", "B"]))
        self.assertFalse(tb._company_columns(frappe._dict(on, view="Account -> Party"), ["A", "B"]))
        self.assertFalse(tb._company_columns(frappe._dict(view="By Account"), ["A", "B"]))
        rows, f = self._build(companies=("A",))
        self.assertFalse(f._company_columns)
        self.assertFalse([r for r in rows if "cv" in r])


class TestCompanyColumnsByParty(unittest.TestCase):
    VALUES = {
        ("Customer", "C1", "A"): _v(od=100),
        ("Customer", "C1", "B"): _v(oc=30),
        ("Supplier", "S1", "A"): _v(oc=50, d=10),
        ("Customer", None, "A"): _v(od=7),     # no party: not a row here
    }

    def _build(self, **kw):
        kw.setdefault("company_columns", 1)
        with mock.patch.object(tb, "_slice", return_value=dict(self.VALUES)) as sl, \
                mock.patch.object(tb, "_resolve_party_names", return_value={}), \
                mock.patch.object(tb, "_company_currency", return_value="INR"):
            rows = tb._build_by_party(_filters("By Party", **kw), ["A", "B"])
        return rows, sl

    def test_parties_keep_each_companys_figure(self):
        rows, sl = self._build()
        self.assertEqual(sl.call_args[0][1], ["party_type", "party", "company"])
        c1 = next(r for r in rows if r.get("party") == "C1")
        self.assertEqual((c1["opening_debit"], c1["opening_credit"]), (70, 0))
        self.assertEqual(c1["cv"], [[100, 0, 0, 0, 100, 0], [0, 30, 0, 0, 0, 30]])
        s1 = next(r for r in rows if r.get("party") == "S1")
        self.assertEqual(s1["cv"], [[0, 50, 10, 0, 0, 40], None])
        t = _total(rows)
        self.assertEqual(t["cv"][1], [0, 30, 0, 0, 0, 30])
        self.assertEqual(len([r for r in rows if not r.get("is_total")]), 2)

    def test_the_consolidated_party_is_as_before(self):
        rows, _sl = self._build()
        with mock.patch.object(tb, "_slice", return_value={
                    ("Customer", "C1"): _v(od=100, oc=30), ("Supplier", "S1"): _v(oc=50, d=10),
                    ("Customer", None): _v(od=7)}), \
                mock.patch.object(tb, "_resolve_party_names", return_value={}), \
                mock.patch.object(tb, "_company_currency", return_value="INR"):
            plain = tb._build_by_party(_filters("By Party"), ["A", "B"])
        strip = lambda rs: [{k: v for k, v in r.items() if k != "cv"} for r in rs]  # noqa: E731
        self.assertEqual(strip(rows), strip(plain))


class TestCompanyCarryShares(unittest.TestCase):

    def test_the_aggregate_gives_every_share_in_one_query(self):
        from dux_voucher.dux_voucher.api import tb_aggregate
        with mock.patch.object(frappe.db, "sql", return_value=[
                frappe._dict(company="A", net=5.0), frappe._dict(company="B", net=-2.0)]) as sql:
            shares = tb_aggregate.unclosed_pl(["A", "B"], "2026-04-01", "2027-03-31",
                                              "2026-04-01", by_company=True)
        self.assertEqual(shares, {"A": 5.0, "B": -2.0})
        self.assertEqual(sql.call_count, 1)
        self.assertIn("GROUP BY agg.company", sql.call_args[0][0])

    def test_live_shares_are_the_per_company_carry(self):
        f = _filters("By Account")
        with mock.patch.object(tb, "_touched_companies", side_effect=lambda cos, _f: list(cos)), \
                mock.patch.object(tb, "_unclosed_pl_net",
                                  side_effect=lambda cos, _f: {"A": 3.0, "B": 0.0}[cos[0]]):
            self.assertEqual(tb._unclosed_pl_shares(["A", "B"], f), {"A": 3.0, "B": 0.0})
        self.assertEqual(tb._unclosed_pl_shares(["A"], _filters("By Account", _pl_reset_date=None)), {})


class TestCompareCompanies(unittest.TestCase):
    """Compare = Company puts each company's closing on the same row.

    Built company by company, each series was keyed by that company's own
    account names, so "Cash - A" and "Cash - B" were two rows and the
    companies never met on one."""

    def _compare(self, **kw):
        t = TestCompanyColumns
        f = frappe._dict(view="By Account", compare="Company",
                         from_date=frappe.utils.getdate("2026-04-01"),
                         to_date=frappe.utils.getdate("2027-03-31"),
                         show_net_values=1, show_group_accounts=1,
                         _pl_reset_date=RESET, **kw)
        with mock.patch.object(tb, "_slice", return_value=dict(t.VALUES)), \
                mock.patch.object(tb, "_account_master", return_value=t.MASTER), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_shares", return_value={}):
            return tb._build_comparison(f, ["A", "B"])

    def test_one_row_per_account_with_a_column_per_company(self):
        cols, rows, msg, _c, _s = self._compare()
        self.assertEqual([c["label"] for c in cols if c["fieldname"].startswith("s")], ["A", "B"])
        cash = [r for r in rows if r.get("label") == "Cash"]
        self.assertEqual(len(cash), 1)
        self.assertEqual((cash[0]["s0"], cash[0]["s1"], cash[0]["variance"]), (130, -40, 170))
        total = rows[-1]
        self.assertEqual((total["s0"], total["s1"]), (0, 0))   # both sets of books tie
        self.assertIn("comparing by company", msg)

    def test_a_group_that_nets_to_nil_keeps_its_accounts_under_it(self):
        t = TestCompanyColumns
        values = dict(t.VALUES)
        values[("Debtors - A",)] = _v(oc=100)        # an advance, against cash of 100 Dr
        values[("Cash - A",)] = _v(od=100)
        values[("Capital - A",)] = _v()
        values[("Cash - B",)] = _v()
        values[("Debtors - B",)] = _v()
        values[("Capital - B",)] = _v()
        f = frappe._dict(view="By Account", compare="Company",
                         from_date=frappe.utils.getdate("2026-04-01"),
                         to_date=frappe.utils.getdate("2027-03-31"),
                         show_net_values=1, show_group_accounts=1, _pl_reset_date=RESET)
        with mock.patch.object(tb, "_slice", return_value=values), \
                mock.patch.object(tb, "_account_master", return_value=t.MASTER), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_shares", return_value={}):
            _cols, rows, _m, _c, _s = tb._build_comparison(f, ["A", "B"])
        labels = [r["label"] for r in rows]
        self.assertIn("Assets", labels)            # nil in both, still the parent
        self.assertLess(labels.index("Assets"), labels.index("Cash"))

    def test_carries_that_cancel_still_close_each_company(self):
        # Last year A lost 50 and B made 50: nil together, and each company's
        # column still needs its own share to come to nil.
        t = TestCompanyColumns
        values = dict(t.VALUES)
        values[("Capital - A",)] = _v(oc=180, d=20, c=50)
        values[("Capital - B",)] = _v(od=80)
        f = frappe._dict(view="By Account", compare="Company",
                         from_date=frappe.utils.getdate("2026-04-01"),
                         to_date=frappe.utils.getdate("2027-03-31"),
                         show_net_values=1, show_group_accounts=1, _pl_reset_date=RESET)
        with mock.patch.object(tb, "_slice", return_value=values), \
                mock.patch.object(tb, "_account_master", return_value=t.MASTER), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_shares", return_value={"A": 50.0, "B": -50.0}):
            _cols, rows, _m, _c, _s = tb._build_comparison(f, ["A", "B"])
        carry = next(r for r in rows if r.get("account") == "__unclosed_pl__")
        self.assertEqual((carry["s0"], carry["s1"]), (50, -50))
        self.assertIn("Profit / Loss", carry["label"])
        self.assertEqual((rows[-1]["s0"], rows[-1]["s1"]), (0, 0))

    def test_the_message_says_when_the_aggregate_was_built(self):
        series = [("A", ["A"], None, None), ("B", ["B"], None, None)]
        _c, _r, msg, _x, _s = tb._comparison_result(
            _filters("By Account"), series, "By Account", "Company", {}, [],
            {"aggregate"}, {"2026-11-20 00:03:08.684921"})
        self.assertIn("monthly aggregate · built 2026-11-20 00:03", msg)
        _c, _r, live, _x, _s = tb._comparison_result(
            _filters("By Account"), series, "By Account", "Company", {}, [], {"live"}, set())
        self.assertNotIn("built", live)


class TestCompanyColumnsApi(unittest.TestCase):

    def test_parties_under_a_control_account_keep_each_companys_figure(self):
        from dux_voucher.dux_voucher.api import trial_balance as api
        values = {
            ("Debtors - A", "Customer", "C1"): _v(od=100),
            ("Debtors - B", "Customer", "C1"): _v(oc=30),
            ("Debtors - A", None, None): _v(od=5),
            ("Cash - A", None, None): _v(od=1),
        }
        f = {"company": ["A", "B"], "from_date": "2026-04-01", "to_date": "2027-03-31",
             "show_net_values": 1, "company_columns": 1}
        with mock.patch.object(api, "require_access"), mock.patch.object(api, "_guard"), \
                mock.patch.object(api, "expand_all", return_value=["A", "B"]), \
                mock.patch.object(tb, "_pl_reset_date", return_value=None), \
                mock.patch.object(tb, "_slice", return_value=values), \
                mock.patch.object(tb, "_resolve_party_names", return_value={}), \
                mock.patch.object(tb, "_default_party_accounts", return_value={}), \
                mock.patch.object(frappe.db, "get_value", return_value="Receivable"), \
                mock.patch.object(frappe, "get_all",
                                  return_value=[("Debtors - A", "A"), ("Debtors - B", "B")]):
            out = api.get_account_parties(filters=f, accounts=["Debtors - A", "Debtors - B"])
        c1 = next(r for r in out if r["party"] == "C1")
        self.assertEqual((c1["opening_debit"], c1["opening_credit"]), (70, 0))
        self.assertEqual(c1["cv"], [[100, 0, 0, 0, 100, 0], [0, 30, 0, 0, 0, 30]])
        un = next(r for r in out if r["is_unattributed"])
        self.assertEqual(un["cv"], [[5, 0, 0, 0, 5, 0], None])

    def test_a_merged_row_resolves_to_the_companys_own_account(self):
        from dux_voucher.dux_voucher.api import trial_balance as api
        master = _master(("Cash - B", "B", "Cash", "Assets - B", "Asset", 0),
                         ("CASH  - B", "B", "CASH ", "Assets - B", "Asset", 0),
                         ("Assets - B", "B", "Assets", None, "Asset", 1),
                         ("Bank - B", "B", "Bank", "Assets - B", "Asset", 0))
        with mock.patch.object(api, "require_access"), mock.patch.object(api, "_guard") as guard, \
                mock.patch.object(api, "_ledger_companies", side_effect=lambda n: set(n)), \
                mock.patch.object(tb, "_account_master", return_value=master):
            self.assertEqual(api.get_company_accounts("B", "cash"), ["Cash - B", "CASH  - B"])
            self.assertEqual(api.get_company_accounts("B", "assets"), [])   # groups: no ledger
        self.assertEqual(guard.call_args[0][0].company, ["B"])

    def test_a_group_company_names_no_account(self):
        # The run's companies are ledger companies. A group named here would
        # pass the guard for the companies beneath it and be read for its own.
        from dux_voucher.dux_voucher.api import trial_balance as api
        with mock.patch.object(api, "require_access"), mock.patch.object(api, "_guard") as guard, \
                mock.patch.object(api, "_ledger_companies", side_effect=lambda n: set(n) - {"Trust"}), \
                mock.patch.object(tb, "_account_master") as master:
            self.assertEqual(api.get_company_accounts("Trust", "cash"), [])
            self.assertEqual(api.get_company_accounts("A", "cash", ["Trust", "A"]), [])
        guard.assert_not_called()
        master.assert_not_called()
        with mock.patch.object(frappe, "get_all", return_value=["A"]) as get_all:
            self.assertEqual(api._ledger_companies(["A", "Trust"]), {"A"})
        self.assertEqual(get_all.call_args.kwargs["filters"],
                         {"name": ["in", ["A", "Trust"]], "is_group": 0})

    def test_a_row_split_off_by_placement_opens_its_own_account(self):
        from dux_voucher.dux_voucher.api import trial_balance as api
        master = TestMergedChart.MASTER
        split = "cash" + tb.KEY_SEP + "bank"
        with mock.patch.object(api, "require_access"), mock.patch.object(api, "_guard"), \
                mock.patch.object(api, "_ledger_companies", side_effect=lambda n: set(n)), \
                mock.patch.object(tb, "_account_master",
                                  side_effect=lambda cos: [a for a in master if a.company in cos]):
            self.assertEqual(api.get_company_accounts("B", split, ["A", "B"]), ["Cash - B"])
            self.assertEqual(api.get_company_accounts("A", "cash", '["A", "B"]'), ["Cash - A"])
            self.assertEqual(api.get_company_accounts("A", split, ["A", "B"]), [])
            # without the run's companies: the account of that name in the company
            self.assertEqual(api.get_company_accounts("B", split), ["Cash - B"])

    def test_parties_resolve_companies_as_the_engine_does(self):
        # A party's figures are placed under the run's companies by position:
        # the endpoint must expand a trust exactly as the engine did.
        from dux_voucher.dux_voucher.api import trial_balance as api
        tree = {"Trust": ["A", "B"], "B": ["B"], "C": ["C"]}
        with mock.patch.object(tb, "expand_company", side_effect=lambda n: tree.get(n, [])):
            sel = ["Trust", "B", "C"]
            self.assertEqual(api.expand_all(sel), ["A", "B", "C"])
            self.assertEqual(api.expand_all(sel),
                             tb.resolve_companies(frappe._dict(company=sel)))
            self.assertEqual(api.expand_all("C"), ["C"])

    def test_a_party_opens_on_the_account_most_of_its_lines_sit_on(self):
        # A By Party row names no account, and the Party Ledger loads only
        # with one beside the party.
        from dux_voucher.dux_voucher.api import trial_balance as api
        with mock.patch.object(api, "require_access") as access, \
                mock.patch.object(api, "_guard") as guard, \
                mock.patch.object(api, "_ledger_companies", side_effect=lambda n: set(n)), \
                mock.patch.object(frappe.db, "sql", return_value=(("Creditors - A",),)) as sql:
            self.assertEqual(api.get_party_account("A", "Supplier", "S1"), "Creditors - A")
        access.assert_called_once()
        self.assertEqual(guard.call_args[0][0].company, ["A"])
        query, params = sql.call_args[0]
        self.assertEqual(params, ("A", "Supplier", "S1"))
        self.assertIn("is_cancelled = 0", query)
        self.assertIn("ORDER BY COUNT(*) DESC", query)

    def test_no_account_for_a_group_a_blank_or_a_party_without_lines(self):
        from dux_voucher.dux_voucher.api import trial_balance as api
        with mock.patch.object(api, "require_access"), mock.patch.object(api, "_guard") as guard, \
                mock.patch.object(api, "_ledger_companies", side_effect=lambda n: set(n) - {"Trust"}), \
                mock.patch.object(frappe.db, "sql", return_value=()) as sql:
            self.assertIsNone(api.get_party_account("Trust", "Supplier", "S1"))
            self.assertIsNone(api.get_party_account("A", "", "S1"))
            guard.assert_not_called()
            sql.assert_not_called()
            self.assertIsNone(api.get_party_account("A", "Supplier", "S1"))
        sql.assert_called_once()


class TestAccountPartyCompany(unittest.TestCase):
    """Account -> Party lists each company's own accounts, and a row says whose:
    a drill across companies opens that company's ledger, not the run's first,
    without a lookup on Account the reader may not be allowed."""

    def test_each_account_row_names_its_company(self):
        master = _master(("Cash - A", "A", "Cash", None, "Asset", 0),
                         ("Creditors - B", "B", "Creditors", None, "Liability", 0, "Payable"))
        values = {
            ("Cash - A", None, None): _v(od=10),
            ("Creditors - B", "Supplier", "S1"): _v(oc=7),
            ("Creditors - B", None, None): _v(oc=3),
        }
        with mock.patch.object(tb, "_slice", return_value=values), \
                mock.patch.object(tb, "_account_master", return_value=master), \
                mock.patch.object(tb, "_default_party_accounts", return_value={}), \
                mock.patch.object(tb, "_resolve_party_names", return_value={}), \
                mock.patch.object(tb, "_company_currency", return_value="INR"), \
                mock.patch.object(tb, "_unclosed_pl_net", return_value=0.0):
            rows = tb._build_account_party(_filters("Account -> Party"), ["A", "B"])
        body = [r for r in rows if not r.get("is_total")]
        accounts = {r["account"]: r for r in body if not r.get("parent_account")}
        self.assertEqual({a: r["account_company"] for a, r in accounts.items()},
                         {"Cash - A": "A", "Creditors - B": "B"})
        # The party and the Unattributed row under it reach it by their account.
        kids = [r for r in body if r.get("parent_account")]
        self.assertEqual(sorted(bool(r["is_unattributed"]) for r in kids), [False, True])
        for r in kids:
            self.assertEqual(accounts[r["parent_account"]]["account_company"], "B")
        # Not "company": the page's row filter searches that.
        self.assertFalse([r for r in body if "company" in r])


class TestCompanyColumnsExcel(unittest.TestCase):

    def _export(self, figure="closing", resolved=("A", "B"), values=None,
                selection='["Trust"]', view="By Account", rows=None):
        import io
        from openpyxl import load_workbook
        if rows is None:
            rows, _f = TestCompanyColumns()._build(values)
        cols = tb._columns_for(frappe._dict(view=view), ["A", "B"])

        def engine(f):
            f._company_columns = True
            f._resolved_companies = list(resolved)
            return cols, rows, "", None, None

        f = (F.replace('["College A"]', selection).replace('"By Account"', f'"{view}"')[:-1]
             + f', "company_figure": "{figure}"}}')
        with mock.patch(ENGINE, side_effect=engine):
            reports_export.export_trial_balance_xlsx(filters=f)
        self.filename = frappe.local.response.filename
        return load_workbook(io.BytesIO(frappe.local.response.filecontent))

    def _find(self, ws, label):
        return next(r for r in range(6, ws.max_row + 1) if ws.cell(row=r, column=1).value == label)

    def test_a_sheet_per_figure_and_the_consolidated_one(self):
        wb = self._export()
        self.assertEqual(wb.sheetnames, ["Closing", "Opening", "Debit", "Credit", "Consolidated"])
        ws = wb["Closing"]
        # The consolidated Total beside the names and frozen with them, so it
        # stays in view however many companies scroll past to its right.
        self.assertEqual([ws.cell(row=5, column=i).value for i in range(1, 5)],
                         ["Account", "Total", "A", "B"])
        self.assertEqual(ws.freeze_panes, "C6")
        r = self._find(ws, "Cash")
        self.assertEqual([ws.cell(row=r, column=i).value for i in range(2, 5)], [90, 130, -40])
        self.assertEqual(ws.cell(row=r, column=3).number_format, reports_export.NUM_FMT_SIGNED)
        t = self._find(ws, "Difference")
        self.assertEqual([ws.cell(row=t, column=i).value for i in range(2, 5)], [None, None, None])
        self.assertIn("each of the 2 companies ties", ws["A3"].value)
        self.assertTrue(self.filename.startswith("Trial Balance by Company - Trust - "))
        cons = wb["Consolidated"]
        self.assertEqual(cons.cell(row=5, column=2).value, "Opening (Dr)")

    def test_debit_and_credit_are_plain_sums(self):
        ws = self._export()["Debit"]
        t = self._find(ws, "Total")
        self.assertEqual([ws.cell(row=t, column=i).value for i in range(2, 5)], [70, 70, None])

    def test_two_companies_out_by_opposite_amounts_are_named(self):
        # A is 10 Dr out and B 10 Cr: the consolidated ties, the companies do not.
        values = dict(TestCompanyColumns.VALUES)
        values[("Capital - A",)] = _v(oc=120, d=20, c=50)
        values[("Capital - B",)] = _v(od=20)
        wb = self._export(values=values)
        ws = wb["Closing"]
        self.assertIn("Balanced", ws["A3"].value)
        self.assertIn("2 of the 2 companies do not tie on their own (see the Difference row)",
                      ws["A3"].value)
        t = self._find(ws, "Difference")
        self.assertEqual([ws.cell(row=t, column=i).value for i in range(2, 5)], [None, 10, -10])
        # counted on the closing, so the other sheets point there
        self.assertIn("(see the Closing sheet)", wb["Debit"]["A3"].value)
        self.assertIn("(see the Closing sheet)", wb["Consolidated"]["A3"].value)

    def test_a_company_with_nothing_is_named_not_given_a_column(self):
        ws = self._export(resolved=("A", "B", "C"))["Closing"]
        self.assertEqual([ws.cell(row=5, column=i).value for i in range(1, 6)],
                         ["Account", "Total", "A", "B", None])
        notes = [str(ws.cell(row=r, column=1).value or "") for r in range(1, ws.max_row + 1)]
        self.assertIn("Not shown, with nothing in this run: C", notes)

    def test_it_opens_on_the_figure_on_screen_and_only_that_sheet(self):
        wb = self._export("opening")
        self.assertEqual(wb.active.title, "Opening")
        self.assertEqual([ws.sheet_view.tabSelected for ws in wb.worksheets],
                         [False, True, False, False, False])

    def test_a_trust_beside_a_college_counts_its_colleges(self):
        # Two entries picked, three companies run: the title and the file
        # name count the companies, as the columns do.
        wb = self._export(resolved=("A", "B", "C"), selection='["Trust", "C"]')
        self.assertEqual(wb["Closing"]["A1"].value, "3 companies")
        self.assertEqual(wb["Consolidated"]["A1"].value, "3 companies")
        self.assertTrue(self.filename.startswith("Trial Balance by Company - 3-companies - "))

    def test_another_figures_sheet_reads_its_status_at_the_close(self):
        wb = self._export()
        self.assertTrue(wb["Closing"]["A3"].value.startswith("Balanced — debit equals credit"))
        for sheet in ("Opening", "Debit", "Credit"):
            self.assertTrue(wb[sheet]["A3"].value.startswith(
                "Balanced at the close — debit equals credit"), wb[sheet]["A3"].value)
        self.assertTrue(wb["Consolidated"]["A3"].value.startswith(
            "Balanced — debit equals credit"))

    def test_by_party_reads_as_a_net_of_parties(self):
        rows, _sl = TestCompanyColumnsByParty()._build()
        wb = self._export(view="By Party", rows=rows)
        ws = wb["Closing"]
        self.assertEqual(ws.cell(row=5, column=1).value, "Party")
        # where the parties stand, and nothing about ties or companies
        self.assertRegex(ws["A3"].value, r"^Net of all parties: \D*30\.00 Dr$")
        self.assertRegex(wb["Opening"]["A3"].value, r"^Net of all parties at the close: \D*30\.00 Dr$")
        # C1 is 100 Dr at A and 30 Cr at B; S1 40 Cr at A
        t = self._find(ws, "Net of parties")
        self.assertEqual([ws.cell(row=t, column=i).value for i in range(2, 5)], [30, 60, -30])
        self.assertGreater(self._find(wb["Debit"], "Total"), 5)   # movement: plain sums

    def test_a_selection_that_comes_to_one_company_names_it(self):
        # A trust and its only college are one company: named, as one picked
        # alone is, not "1 companies".
        wb = self._export(resolved=("A",), selection='["Trust", "A"]')
        self.assertEqual(wb.sheetnames, ["Trial Balance"])
        self.assertEqual(wb.active["A1"].value, "A")
        self.assertTrue(self.filename.startswith("Trial Balance - A - "), self.filename)


class TestWorkbookPrint(unittest.TestCase):

    def test_the_six_column_sheet_prints_one_page_wide_not_one_page(self):
        import io
        from openpyxl import load_workbook
        rows, _f = TestCompanyColumns()._build(company_columns=0)
        cols = tb._columns_for(frappe._dict(view="By Account"), ["A", "B"])
        with mock.patch(ENGINE, return_value=(cols, rows, "", None, None)):
            reports_export.export_trial_balance_xlsx(filters=F)
        ws = load_workbook(io.BytesIO(frappe.local.response.filecontent))["Trial Balance"]
        self.assertEqual((ws.page_setup.fitToWidth, ws.page_setup.fitToHeight), (1, 0))
        self.assertTrue(ws.sheet_properties.pageSetUpPr.fitToPage)
        ws = TestCompanyColumnsExcel()._export()["Consolidated"]
        self.assertEqual((ws.page_setup.fitToWidth, ws.page_setup.fitToHeight), (1, 0))


if __name__ == "__main__":
    unittest.main()
