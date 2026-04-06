/* ============================================================
   dux_ledger.js  —  Tally-style Ledger Statement
   Dux DigiTech  —  dux_voucher app
   ============================================================ */

frappe.pages["dux-ledger"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Ledger Statement",
			single_column: true,
		});
		window._dux_ledger_instance = new DuxLedger(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' +
				e.message +
				"</div>"
		);
		console.error("dux-ledger:", e);
	}
};

frappe.pages["dux-ledger"].on_page_show = function (wrapper) {
	if (window._dux_ledger_instance && frappe.route_options) {
		window._dux_ledger_instance.applyRouteOptions(frappe.route_options);
		frappe.route_options = null;
	}
};

/* ============================================================
   DuxLedger
   ============================================================ */
class DuxLedger {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();

		page.add_inner_button("← Home", function () {
			window.location.href = "/rgi-home";
		});
	}

	/* ── Styles ──────────────────────────────────────────────── */
	_injectStyles() {
		if (document.getElementById("dl-styles")) return;
		var s = document.createElement("style");
		s.id = "dl-styles";
		s.textContent = `
/* ── Page wrapper ── */
.dl-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}

/* ── Filter card ── */
.dl-filter-card{
  background:#fff;border:1px solid #e5e7eb;border-radius:10px;
  padding:20px 24px;margin-bottom:20px;
  display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px;
}
.dl-fg{display:flex;flex-direction:column;gap:5px}
.dl-fg label{
  font-size:10px;font-weight:700;color:#6b7280;
  text-transform:uppercase;letter-spacing:.08em;
}
.dl-fg select,.dl-fg input[type=text],.dl-fg input[type=date]{
  height:36px;border:1px solid #e5e7eb;border-radius:7px;
  padding:0 11px;font-size:13px;color:#111827;
  background:#fff;outline:none;transition:border .15s;
  font-family:inherit;box-sizing:border-box;
}
.dl-fg select:focus,.dl-fg input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.08)}
#dl-co-sel{min-width:220px}
#dl-acc-inp{min-width:260px}
#dl-from,#dl-to{width:148px}

/* Search dropdown */
.dl-acc-drop{
  position:absolute;z-index:999;background:#fff;
  border:1px solid #e5e7eb;border-radius:8px;
  box-shadow:0 8px 24px rgba(0,0,0,.10);
  min-width:320px;max-height:280px;overflow-y:auto;
  margin-top:2px;
}
.dl-acc-drop-item{
  padding:9px 14px;cursor:pointer;font-size:13px;
  display:flex;flex-direction:column;gap:2px;
  border-bottom:1px solid #f3f4f6;
}
.dl-acc-drop-item:last-child{border-bottom:none}
.dl-acc-drop-item:hover{background:#f0f4ff}
.dl-acc-drop-item .dl-acc-name{font-weight:500;color:#111827}
.dl-acc-drop-item .dl-acc-meta{font-size:11px;color:#9ca3af;font-family:monospace}
.dl-acc-drop-empty{padding:14px;font-size:13px;color:#9ca3af;text-align:center}

.dl-fg-acc{position:relative}
.dl-btn-row{display:flex;gap:8px;align-items:flex-end;padding-bottom:0}
.dl-btn{
  height:36px;padding:0 18px;border-radius:7px;
  font-size:13px;font-weight:600;cursor:pointer;
  border:1px solid #e5e7eb;font-family:inherit;
  transition:all .15s;
}
.dl-btn-primary{
  background:#2563eb;border-color:#2563eb;color:#fff;
}
.dl-btn-primary:hover{background:#1d4ed8;border-color:#1d4ed8}
.dl-btn-secondary{background:#fff;color:#374151}
.dl-btn-secondary:hover{background:#f9fafb}
#dl-print-btn{display:none}

/* ── Placeholder ── */
.dl-placeholder{
  text-align:center;padding:64px 20px;
  color:#9ca3af;font-size:14px;
}
.dl-placeholder strong{color:#6b7280}

/* ── Report card ── */
.dl-report-card{
  background:#fff;border:1px solid #e5e7eb;border-radius:10px;
  overflow:hidden;
}

/* ── Report header ── */
.dl-rpt-hdr{
  padding:18px 24px 14px;
  border-bottom:1px solid #f3f4f6;
}
.dl-rpt-co{
  font-size:16px;font-weight:700;color:#111827;
  margin-bottom:3px;letter-spacing:-.01em;
}
.dl-rpt-ledger-row{
  display:flex;align-items:center;gap:8px;
  font-size:13px;color:#374151;margin-bottom:3px;
}
.dl-rpt-ledger-row strong{font-weight:600}
.dl-acc-type-badge{
  font-size:10px;font-weight:600;
  background:#eff6ff;color:#2563eb;
  border-radius:4px;padding:2px 7px;
  font-family:inherit;letter-spacing:.03em;
}
.dl-rpt-period{
  font-size:11px;color:#9ca3af;
  font-family:'SFMono-Regular',Consolas,monospace;
  display:flex;align-items:center;gap:8px;
}
.dl-rpt-period span{
  background:#f9fafb;border:1px solid #f3f4f6;
  border-radius:4px;padding:1px 7px;
}

/* ── Table ── */
.dl-tbl-wrap{overflow-x:auto}
.dl-tbl{
  width:100%;border-collapse:collapse;
  font-size:12.5px;
}
.dl-tbl thead th{
  font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:#9ca3af;
  padding:9px 16px;background:#fafafa;
  border-bottom:1px solid #f3f4f6;
  white-space:nowrap;font-family:inherit;
}
.dl-tbl thead th.r{text-align:right}

/* ── Opening / Closing balance rows ── */
.dl-tr-ob td,.dl-tr-cb td{
  padding:10px 16px;background:#f9fafb;
  font-size:12px;font-family:inherit;
}
.dl-tr-ob td{border-bottom:1px solid #f3f4f6}
.dl-tr-cb td{border-top:2px solid #e5e7eb}
.dl-ob-label,.dl-cb-label{
  font-weight:700;color:#374151;
  text-transform:uppercase;font-size:10px;letter-spacing:.08em;
}

/* ── Entry rows ── */
.dl-tr-e td{
  padding:10px 16px;border-bottom:1px solid #f9fafb;
  vertical-align:top;
}
.dl-tr-e:hover td{background:#fafbff}

/* ── Remarks sub-row ── */
.dl-tr-r td{
  padding:2px 16px 9px 32px;border-bottom:1px solid #f9fafb;
  font-size:11px;color:#9ca3af;font-style:italic;
  line-height:1.5;
}

/* ── Total row ── */
.dl-tr-tot td{
  padding:10px 16px;border-top:2px solid #e5e7eb;
  font-size:12.5px;font-weight:700;
}
.dl-tot-label{
  text-align:right;font-size:10px;color:#9ca3af;
  text-transform:uppercase;letter-spacing:.08em;font-weight:700;
}

/* ── Column widths ── */
.dl-c-date{width:80px;color:#9ca3af;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px}
.dl-c-part{min-width:180px}
.dl-c-vt{width:130px;white-space:nowrap}
.dl-c-vno{width:130px;white-space:nowrap}
.dl-c-amt{width:110px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.dl-c-bal{width:120px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}

/* ── To / By ── */
.dl-to{color:#2563eb;font-weight:600;font-size:11px;margin-right:3px}
.dl-by{color:#059669;font-weight:600;font-size:11px;margin-right:3px}
.dl-contra-name{color:#111827;font-weight:500;font-size:13px}

/* ── Voucher No link ── */
.dl-vno{
  color:#2563eb;text-decoration:none;font-size:12px;
  font-family:'SFMono-Regular',Consolas,monospace;
}
.dl-vno:hover{text-decoration:underline}

/* ── Amounts ── */
.dl-dr{color:#dc2626;font-weight:500}
.dl-cr{color:#059669;font-weight:500}
.dl-nil{color:#d1d5db}
.dl-bal-dr{color:#dc2626;font-weight:700}
.dl-bal-cr{color:#059669;font-weight:700}
.dl-bsuf{font-size:9px;margin-left:2px;font-weight:600;opacity:.7;letter-spacing:.04em}

/* ── Voucher type pills ── */
.dl-pill{
  display:inline-block;font-size:10px;font-weight:700;
  padding:3px 8px;border-radius:5px;letter-spacing:.03em;
  white-space:nowrap;font-family:inherit;
}
.dl-pill-pv{background:#eff6ff;color:#1d4ed8}
.dl-pill-rv{background:#f0fdf4;color:#166534}
.dl-pill-jv{background:#fffbeb;color:#92400e}
.dl-pill-cv{background:#f5f3ff;color:#5b21b6}
.dl-pill-pe{background:#fdf4ff;color:#7e22ce}
.dl-pill-other{background:#f3f4f6;color:#4b5563;border:1px solid #e5e7eb}

/* ── Print ── */
@media print{
  *{overflow:visible!important}
  .dl-filter-card,.dl-no-print,.page-head,
  .layout-side-section,.navbar,header,
  .dl-btn,#dl-print-btn{display:none!important}
  .dl-wrap{padding:0}
  .dl-report-card{border:none;border-radius:0;box-shadow:none}
  .dl-tbl{font-size:11px}
  .dl-tr-e td,.dl-tr-r td{padding:5px 10px}
  .dl-pill{-webkit-print-color-adjust:exact;print-color-adjust:exact}
  body,html{background:#fff!important;margin:0;padding:0}
  .layout-main{padding:0!important}
  .page-head{display:none!important}
}
		`;
		document.head.appendChild(s);
	}

	/* ── Layout ──────────────────────────────────────────────── */
	_renderLayout() {
		$(this.wrapper)
			.find(".layout-main-section")
			.html(`
<div class="dl-wrap">

  <!-- Filter card -->
  <div class="dl-filter-card dl-no-print">
    <div class="dl-fg">
      <label>Company</label>
      <select id="dl-co-sel"><option value="">Select company…</option></select>
    </div>
    <div class="dl-fg dl-fg-acc">
      <label>Account / Ledger</label>
      <input id="dl-acc-inp" type="text" placeholder="Type to search accounts & parties…" autocomplete="off" style="min-width:280px">
      <div class="dl-acc-drop" id="dl-acc-drop" style="display:none"></div>
    </div>
    <div class="dl-fg">
      <label>From</label>
      <input id="dl-from" type="date">
    </div>
    <div class="dl-fg">
      <label>To</label>
      <input id="dl-to" type="date">
    </div>
    <div class="dl-btn-row">
      <button class="dl-btn dl-btn-primary" id="dl-show-btn">Show</button>
      <button class="dl-btn dl-btn-secondary dl-no-print" id="dl-print-btn">Print</button>
    </div>
  </div>

  <!-- Report area -->
  <div id="dl-area">
    <div class="dl-placeholder">
      Select a company and account, then click <strong>Show</strong>.
    </div>
  </div>

</div>
		`);
	}

	/* ── Events ──────────────────────────────────────────────── */
	_bindEvents() {
		var self = this;

		_gel("dl-co-sel").addEventListener("change", function () {
			_gel("dl-acc-inp").value = "";
			_gel("dl-acc-drop").style.display = "none";
		});

		// Account search with debounce
		_gel("dl-acc-inp").addEventListener(
			"input",
			_debounce(function () {
				var co = _gel("dl-co-sel").value;
				var txt = this.value.trim();
				if (co && txt.length >= 2) {
					self._searchAccounts(co, txt);
				} else {
					_gel("dl-acc-drop").style.display = "none";
				}
			}, 280)
		);

		// Close dropdown on outside click
		document.addEventListener("click", function (e) {
			if (!e.target.closest(".dl-fg-acc")) {
				_gel("dl-acc-drop").style.display = "none";
			}
		});

		_gel("dl-show-btn").addEventListener("click", function () {
			self.fetchReport();
		});

		_gel("dl-print-btn").addEventListener("click", function () {
			window.print();
		});

		["dl-co-sel", "dl-acc-inp", "dl-from", "dl-to"].forEach(function (id) {
			_gel(id).addEventListener("keydown", function (ev) {
				if (ev.key === "Enter") self.fetchReport();
			});
		});
	}

	/* ── Default dates — Indian FY Apr 1 → today ─────────────── */
	_setDefaultDates() {
		var now = new Date();
		var m = now.getMonth();
		var yr = now.getFullYear();
		var fyStart = m >= 3 ? yr : yr - 1;
		_gel("dl-from").value = fyStart + "-04-01";
		_gel("dl-to").value = now.toISOString().split("T")[0];
	}

	/* ── Load companies (respects User Permissions) ──────────── */
	_loadCompanies() {
		var self = this;
		frappe.call({
			method: "frappe.auth.get_logged_user",
			callback: function (r) {
				var email = r.message;
				if (!email || email === "Guest") return;
				frappe.call({
					method: "frappe.client.get_list",
					args: {
						doctype: "User Permission",
						filters: [
							["user", "=", email],
							["allow", "=", "Company"],
						],
						fields: ["for_value"],
						limit_page_length: 200,
					},
					callback: function (r2) {
						var items = r2.message || [];
						if (items.length) {
							self._populateCompanies(
								items.map(function (p) {
									return p.for_value;
								})
							);
						} else {
							frappe.call({
								method: "frappe.client.get_list",
								args: {
									doctype: "Company",
									filters: [["is_group", "=", 0]],
									fields: ["name"],
									limit_page_length: 200,
									order_by: "name asc",
								},
								callback: function (r3) {
									self._populateCompanies(
										(r3.message || []).map(function (c) {
											return c.name;
										})
									);
								},
							});
						}
					},
				});
			},
		});
	}

	_populateCompanies(names) {
		var sel = _gel("dl-co-sel");
		names.forEach(function (n) {
			sel.innerHTML += `<option value="${_esc(n)}">${_esc(n)}</option>`;
		});
	}

	/* ── Account / Party search ──────────────────────────────── */
	_searchAccounts(company, txt) {
		var self = this;
		frappe.call({
			method: "dux_voucher.dux_voucher.api.reports_api.search_ledger",
			args: { company: company, search_txt: txt },
			callback: function (r) {
				var results = r.message || [];
				var drop = _gel("dl-acc-drop");
				if (!results.length) {
					drop.innerHTML =
						'<div class="dl-acc-drop-empty">No matches found</div>';
					drop.style.display = "block";
					return;
				}
				drop.innerHTML = results
					.map(function (item) {
						return `
<div class="dl-acc-drop-item" data-value="${_esc(item.value)}" data-label="${_esc(item.label)}">
  <span class="dl-acc-name">${_esc(item.label)}</span>
  <span class="dl-acc-meta">${_esc(item.meta)}</span>
</div>`;
					})
					.join("");
				drop.style.display = "block";
				// Click to select
				drop.querySelectorAll(".dl-acc-drop-item").forEach(function (el) {
					el.addEventListener("click", function () {
						_gel("dl-acc-inp").value = el.dataset.value;
						drop.style.display = "none";
						self.fetchReport();
					});
				});
			},
		});
	}

	/* ── Route options ───────────────────────────────────────── */
	applyRouteOptions(opts) {
		if (opts.company) _gel("dl-co-sel").value = opts.company;
		if (opts.account) _gel("dl-acc-inp").value = opts.account;
		if (opts.from_date) _gel("dl-from").value = opts.from_date;
		if (opts.to_date) _gel("dl-to").value = opts.to_date;
		if (opts.company && opts.account) this.fetchReport();
	}

	/* ── Fetch report ────────────────────────────────────────── */
	fetchReport() {
		var company = _gel("dl-co-sel").value;
		var account = _gel("dl-acc-inp").value.trim();
		var from_date = _gel("dl-from").value;
		var to_date = _gel("dl-to").value;

		if (!company) {
			frappe.msgprint({ message: "Please select a Company.", indicator: "orange" });
			return;
		}
		if (!account) {
			frappe.msgprint({
				message: "Please enter an Account or Party name.",
				indicator: "orange",
			});
			return;
		}
		if (!from_date || !to_date) {
			frappe.msgprint({ message: "Please set both dates.", indicator: "orange" });
			return;
		}

		_gel("dl-area").innerHTML =
			'<div class="dl-placeholder">Loading…</div>';
		_gel("dl-print-btn").style.display = "none";

		var self = this;
		frappe.call({
			method: "dux_voucher.dux_voucher.api.reports_api.get_ledger_statement",
			args: { company, account, from_date, to_date },
			callback: function (r) {
				if (r.message) {
					self._render(r.message);
					_gel("dl-print-btn").style.display = "inline-block";
				} else {
					_gel("dl-area").innerHTML =
						'<div class="dl-placeholder">No data found for this account and period.</div>';
				}
			},
			error: function () {
				_gel("dl-area").innerHTML =
					'<div class="dl-placeholder" style="color:#dc2626">Could not load report. Please check the account name and try again.</div>';
			},
		});
	}

	/* ── Render ──────────────────────────────────────────────── */
	_render(d) {
		var rows = "";

		// Opening Balance row
		rows += `
<tr class="dl-tr-ob">
  <td colspan="4"><span class="dl-ob-label">Opening Balance</span></td>
  <td class="dl-c-amt"></td>
  <td class="dl-c-amt"></td>
  <td class="dl-c-bal">${_bal(d.opening_balance, d.opening_type)}</td>
</tr>`;

		if (!d.rows.length) {
			rows += `<tr><td colspan="7" class="dl-placeholder" style="padding:32px">No transactions in this period.</td></tr>`;
		}

		d.rows.forEach(function (row) {
			var pCls = row.prefix === "To" ? "dl-to" : "dl-by";
			var drHtml =
				row.debit > 0
					? `<span class="dl-dr">${_fmt(row.debit)}</span>`
					: `<span class="dl-nil">—</span>`;
			var crHtml =
				row.credit > 0
					? `<span class="dl-cr">${_fmt(row.credit)}</span>`
					: `<span class="dl-nil">—</span>`;

			rows += `
<tr class="dl-tr-e">
  <td class="dl-c-date">${_esc(row.posting_date)}</td>
  <td class="dl-c-part">
    <span class="${pCls}">${row.prefix}</span>
    <span class="dl-contra-name">${_esc(row.contra)}</span>
  </td>
  <td class="dl-c-vt">${_pill(row.voucher_type)}</td>
  <td class="dl-c-vno">
    <a class="dl-vno" href="${_esc(row.voucher_url)}" target="_blank">${_esc(row.voucher_no)}</a>
  </td>
  <td class="dl-c-amt">${drHtml}</td>
  <td class="dl-c-amt">${crHtml}</td>
  <td class="dl-c-bal">${_bal(row.balance, row.balance_type)}</td>
</tr>`;

			if (row.remarks) {
				rows += `<tr class="dl-tr-r"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
			}
		});

		// Closing Balance row
		rows += `
<tr class="dl-tr-cb">
  <td colspan="4"><span class="dl-cb-label">Closing Balance</span></td>
  <td class="dl-c-amt"></td>
  <td class="dl-c-amt"></td>
  <td class="dl-c-bal" style="font-size:13px">${_bal(d.closing_balance, d.closing_type)}</td>
</tr>`;

		// Totals row
		rows += `
<tr class="dl-tr-tot">
  <td colspan="4" class="dl-tot-label">Period Totals</td>
  <td class="dl-c-amt"><span class="dl-dr">${_fmt(d.total_debit)}</span></td>
  <td class="dl-c-amt"><span class="dl-cr">${_fmt(d.total_credit)}</span></td>
  <td class="dl-c-bal"></td>
</tr>`;

		var badge = d.account_type
			? `<span class="dl-acc-type-badge">${_esc(d.account_type)}</span>`
			: "";

		_gel("dl-area").innerHTML = `
<div class="dl-report-card">
  <div class="dl-rpt-hdr">
    <div class="dl-rpt-co">${_esc(d.company)}</div>
    <div class="dl-rpt-ledger-row">
      <span>Ledger:</span>
      <strong>${_esc(d.account_name)}</strong>
      ${badge}
    </div>
    <div class="dl-rpt-period">
      <span>${_esc(d.from_date)}</span>
      <span style="color:#d1d5db">→</span>
      <span>${_esc(d.to_date)}</span>
      <span style="color:#d1d5db">·</span>
      <span>${d.row_count} transaction${d.row_count !== 1 ? "s" : ""}</span>
    </div>
  </div>
  <div class="dl-tbl-wrap">
    <table class="dl-tbl">
      <thead>
        <tr>
          <th class="dl-c-date">Date</th>
          <th class="dl-c-part">Particulars</th>
          <th class="dl-c-vt">Vch Type</th>
          <th class="dl-c-vno">Vch No</th>
          <th class="dl-c-amt r">Debit</th>
          <th class="dl-c-amt r">Credit</th>
          <th class="dl-c-bal r">Balance</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
	}
}

/* ============================================================
   Utilities
   ============================================================ */
function _gel(id) {
	return document.getElementById(id);
}

function _fmt(val) {
	return new Intl.NumberFormat("en-IN", {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
	}).format(val || 0);
}

function _bal(val, type) {
	if (!val && val !== 0)
		return '<span class="dl-nil">0.00</span>';
	if (val === 0)
		return '<span style="color:#9ca3af;font-family:monospace">0.00</span>';
	var cls = type === "Dr" ? "dl-bal-dr" : "dl-bal-cr";
	return `<span class="${cls}">${_fmt(val)}<span class="dl-bsuf">${type}</span></span>`;
}

function _pill(vtype) {
	var map = {
		"Payment Voucher": "dl-pill-pv",
		"Receipt Voucher": "dl-pill-rv",
		"Journal Entry": "dl-pill-jv",
		"Contra Entry": "dl-pill-cv",
		"Payment Entry": "dl-pill-pe",
		"Receipt Entry": "dl-pill-rv",
	};
	var cls = map[vtype] || "dl-pill-other";
	return `<span class="dl-pill ${cls}">${_esc(vtype)}</span>`;
}

function _esc(str) {
	if (str === null || str === undefined) return "";
	return String(str)
		.replace(/&/g, "&amp;")
		.replace(/</g, "&lt;")
		.replace(/>/g, "&gt;")
		.replace(/"/g, "&quot;");
}

function _debounce(fn, ms) {
	var t;
	return function () {
		var ctx = this,
			args = arguments;
		clearTimeout(t);
		t = setTimeout(function () {
			fn.apply(ctx, args);
		}, ms);
	};
}
