// Dux Trial Balance — filters and presentation.
//
// Deliberate differences from ERPNext's Trial Balance:
//   * Fiscal Year fills the dates and then gets out of the way. It never
//     clamps them, so a period may span two fiscal years.
//   * Company is a multi-select that accepts GROUP companies, so picking a
//     trust pulls in everything beneath it.
//   * One report, four groupings, chosen by the View filter.

frappe.query_reports["Dux Trial Balance"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company / Trust"),
			fieldtype: "MultiSelectList",
			options: "Company",
			reqd: 1,
			default: [frappe.defaults.get_user_default("Company")].filter(Boolean),
			get_data: function (txt) {
				return frappe.db.get_link_options("Company", txt);
			},
		},
		{
			fieldname: "view",
			label: __("View"),
			fieldtype: "Select",
			options: ["By Account", "By Party", "Account -> Party", "By Company"].join("\n"),
			default: "By Account",
			reqd: 1,
		},
		{
			fieldname: "fiscal_year",
			label: __("Fiscal Year"),
			fieldtype: "Link",
			options: "Fiscal Year",
			// Not reqd, and NOT used by the backend — it only fills the dates.
			// The site has overlapping fiscal years, so the user picks the one
			// they mean rather than us guessing from a date.
			on_change: function (query_report) {
				const fy = query_report.get_filter_value("fiscal_year");
				if (!fy) return;
				frappe.model.with_doc("Fiscal Year", fy, function () {
					const doc = frappe.model.get_doc("Fiscal Year", fy);
					query_report.set_filter_value({
						from_date: doc.year_start_date,
						to_date: doc.year_end_date,
					});
				});
			},
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.add_months(frappe.datetime.get_today(), -12),
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			reqd: 1,
			default: frappe.datetime.get_today(),
		},
		{
			fieldname: "cost_center",
			label: __("Cost Center"),
			fieldtype: "MultiSelectList",
			options: "Cost Center",
			get_data: function (txt) {
				const co = frappe.query_report.get_filter_value("company");
				return frappe.db.get_link_options("Cost Center", txt, {
					company: Array.isArray(co) ? co[0] : co,
				});
			},
		},
		{
			fieldname: "project",
			label: __("Project"),
			fieldtype: "MultiSelectList",
			options: "Project",
			get_data: function (txt) {
				return frappe.db.get_link_options("Project", txt);
			},
		},
		{
			fieldname: "show_net_values",
			label: __("Net opening / closing"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "show_group_accounts",
			label: __("Show group accounts"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "show_zero_values",
			label: __("Show zero rows"),
			fieldtype: "Check",
			default: 0,
		},
		{
			// P&L accounts close annually, so their opening resets at the
			// fiscal-year boundary. Tick this to carry prior years forward
			// instead — useful only where no Period Closing Voucher has run.
			fieldname: "show_unclosed_fy_pl_balances",
			label: __("Carry prior-year P&L into opening"),
			fieldtype: "Check",
			default: 0,
		},
		{
			fieldname: "control_accounts_only",
			label: __("Control accounts only"),
			fieldtype: "Check",
			default: 0,
			depends_on: "eval:doc.view=='Account -> Party'",
		},
	],

	tree: true,
	name_field: "account",
	parent_field: "parent_account",
	initial_depth: 3,

	formatter: function (value, row, column, data, default_formatter) {
		let out = default_formatter(value, row, column, data);

		if (!data) return out;

		// Total row: bold, and colour the tie state.
		if (data.is_total) {
			out = `<span style="font-weight:700">${out}</span>`;
			return out;
		}

		const label_col = ["account_name", "party", "company"].includes(column.fieldname);

		// An Unattributed row is not an error, but it should never be
		// mistaken for a party either.
		if (label_col && data.is_unattributed) {
			return `<span style="color:#647A8A;font-style:italic">${out}</span>`;
		}

		// A party sitting on a control account its type does not belong to.
		if (label_col && data.mismatch) {
			return `<span style="color:#A65A00;font-weight:600" title="${__(
				"This party type does not normally belong on this account type"
			)}">&#9888; ${out}</span>`;
		}

		// A computed carry-forward is not a real account and must never be
		// mistaken for one.
		if (data.is_computed) {
			return `<span style="color:#A65A00;font-style:italic" title="${__(
				"Computed, not a posted account. Prior-year P&L that no Period Closing Voucher has moved to reserves."
			)}">${out}</span>`;
		}

		// Group accounts carry the structure — make the tree readable.
		if (label_col && data.is_group_account) {
			out = `<span style="font-weight:600">${out}</span>`;
		}

		return out;
	},

	onload: function (report) {
		report.page.add_inner_button(__("Open Ledger"), function () {
			frappe.msgprint(
				__("Select a row first, then use the account or party link to open its ledger.")
			);
		});
	},
};
