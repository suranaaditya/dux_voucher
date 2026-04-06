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
				e.message + "</div>"
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
		this.wrapper    = wrapper;
		this.page       = page;
		this._selected  = null; // {type, value, party_type, account, label}
		this._lastData  = null; // last API response for print

		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();

		page.add_inner_button("← Home", function () {
			window.location.href = "/rgi-home";
		});
	}

	/* ── Styles ───────────────────────────────────────────────── */
	_injectStyles() {
		if (document.getElementById("dl-styles")) return;
		var s = document.createElement("style");
		s.id = "dl-styles";
		s.textContent = `
.dl-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}

/* Filter card */
.dl-filter-card{
  background:#fff;border:1px solid #e5e7eb;border-radius:10px;
  padding:20px 24px;margin-bottom:20px;
  display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px;
}
.dl-fg{display:flex;flex-direction:column;gap:5px}
.dl-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.dl-fg select,.dl-fg input[type=text],.dl-fg input[type=date]{
  height:36px;border:1px solid #e5e7eb;border-radius:7px;
  padding:0 11px;font-size:13px;color:#111827;background:#fff;
  outline:none;transition:border .15s;font-family:inherit;box-sizing:border-box;
}
.dl-fg select:focus,.dl-fg input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.08)}
#dl-co-sel{min-width:220px}
#dl-acc-inp{min-width:280px}
#dl-from,#dl-to{width:148px}

/* Search dropdown */
.dl-drop{
  position:absolute;z-index:9999;background:#fff;
  border:1px solid #e5e7eb;border-radius:8px;
  box-shadow:0 8px 28px rgba(0,0,0,.12);
  min-width:340px;max-height:300px;overflow-y:auto;
  margin-top:3px;left:0;
}
.dl-drop-section{
  padding:6px 12px 3px;font-size:10px;font-weight:700;
  color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;
  border-bottom:1px solid #f3f4f6;background:#fafafa;
}
.dl-drop-item{
  padding:9px 14px;cursor:pointer;
  display:flex;flex-direction:column;gap:2px;
  border-bottom:1px solid #f9fafb;
}
.dl-drop-item:last-child{border-bottom:none}
.dl-drop-item:hover{background:#f0f4ff}
.dl-drop-label{font-size:13px;font-weight:500;color:#111827}
.dl-drop-meta{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace}
.dl-drop-empty{padding:16px;font-size:13px;color:#9ca3af;text-align:center}

/* Party type badge in search input */
.dl-fg-acc{position:relative}
.dl-sel-pill{
  display:inline-flex;align-items:center;gap:5px;
  background:#eff6ff;border:1px solid #bfdbfe;
  border-radius:5px;padding:2px 8px 2px 8px;
  font-size:12px;font-weight:500;color:#1d4ed8;
  margin-bottom:4px;cursor:pointer;
}
.dl-sel-pill-x{font-size:14px;line-height:1;color:#93c5fd;margin-left:2px}
.dl-sel-pill-x:hover{color:#1d4ed8}

/* Buttons */
.dl-btn-row{display:flex;gap:8px;align-items:flex-end}
.dl-btn{
  height:36px;padding:0 18px;border-radius:7px;font-size:13px;
  font-weight:600;cursor:pointer;border:1px solid #e5e7eb;
  font-family:inherit;transition:all .15s;
}
.dl-btn-primary{background:#2563eb;border-color:#2563eb;color:#fff}
.dl-btn-primary:hover{background:#1d4ed8}
.dl-btn-secondary{background:#fff;color:#374151}
.dl-btn-secondary:hover{background:#f9fafb}
#dl-print-btn{display:none}

/* Placeholder */
.dl-placeholder{text-align:center;padding:64px 20px;color:#9ca3af;font-size:14px}
.dl-placeholder strong{color:#6b7280}

/* Report card */
.dl-report-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}

/* Report header */
.dl-rpt-hdr{padding:18px 24px 14px;border-bottom:1px solid #f3f4f6}
.dl-rpt-co{font-size:16px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.01em}
.dl-rpt-ledger-row{display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;margin-bottom:4px}
.dl-rpt-ledger-row strong{font-weight:600}
.dl-acc-type-badge{
  font-size:10px;font-weight:700;background:#eff6ff;color:#2563eb;
  border-radius:4px;padding:2px 7px;letter-spacing:.03em;
}
.dl-party-badge{
  font-size:10px;font-weight:700;background:#f0fdf4;color:#166534;
  border-radius:4px;padding:2px 7px;letter-spacing:.03em;
}
.dl-rpt-period{
  font-size:11px;color:#9ca3af;
  font-family:'SFMono-Regular',Consolas,monospace;
  display:flex;align-items:center;gap:8px;
}
.dl-rpt-period span{background:#f9fafb;border:1px solid #f3f4f6;border-radius:4px;padding:1px 7px}

/* Table */
.dl-tbl-wrap{overflow-x:auto}
.dl-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.dl-tbl thead th{
  font-size:10px;font-weight:700;text-transform:uppercase;
  letter-spacing:.08em;color:#9ca3af;
  padding:9px 16px;background:#fafafa;
  border-bottom:1px solid #f3f4f6;
  white-space:nowrap;font-family:inherit;
}
.dl-tbl thead th.r{text-align:right}

/* Opening / Closing */
.dl-tr-ob td,.dl-tr-cb td{padding:10px 16px;background:#f9fafb;font-size:12px}
.dl-tr-ob td{border-bottom:1px solid #f3f4f6}
.dl-tr-cb td{border-top:2px solid #e5e7eb}
.dl-ob-label,.dl-cb-label{font-weight:700;color:#374151;text-transform:uppercase;font-size:10px;letter-spacing:.08em}

/* Entry rows */
.dl-tr-e td{padding:10px 16px;border-bottom:1px solid #f9fafb;vertical-align:top}
.dl-tr-e:hover td{background:#fafbff}

/* Remarks */
.dl-tr-r td{
  padding:1px 16px 9px 32px;border-bottom:1px solid #f9fafb;
  font-size:11px;color:#9ca3af;font-style:italic;line-height:1.5;
}

/* Totals */
.dl-tr-tot td{padding:10px 16px;border-top:2px solid #e5e7eb;font-size:12.5px;font-weight:700}
.dl-tot-label{text-align:right;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;font-weight:700}

/* Columns */
.dl-c-date{width:80px;color:#9ca3af;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px}
.dl-c-part{min-width:180px}
.dl-c-vt{width:130px;white-space:nowrap}
.dl-c-vno{width:130px;white-space:nowrap}
.dl-c-amt{width:110px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.dl-c-bal{width:120px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}

/* To / By */
.dl-to{color:#2563eb;font-weight:700;font-size:11px;margin-right:4px}
.dl-by{color:#059669;font-weight:700;font-size:11px;margin-right:4px}
.dl-contra-name{color:#111827;font-weight:500;font-size:13px}

/* Voucher No */
.dl-vno{color:#2563eb;text-decoration:none;font-size:12px;font-family:'SFMono-Regular',Consolas,monospace}
.dl-vno:hover{text-decoration:underline}

/* Amounts */
.dl-dr{color:#dc2626;font-weight:500}
.dl-cr{color:#059669;font-weight:500}
.dl-nil{color:#d1d5db}
.dl-bal-dr{color:#dc2626;font-weight:700}
.dl-bal-cr{color:#059669;font-weight:700}
.dl-bsuf{font-size:9px;margin-left:2px;font-weight:700;opacity:.65;letter-spacing:.04em}

/* Pills */
.dl-pill{display:inline-block;font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;letter-spacing:.03em;white-space:nowrap;font-family:inherit}
.dl-pill-pv{background:#eff6ff;color:#1d4ed8}
.dl-pill-rv{background:#f0fdf4;color:#166534}
.dl-pill-jv{background:#fffbeb;color:#92400e}
.dl-pill-cv{background:#f5f3ff;color:#5b21b6}
.dl-pill-pi{background:#fff7ed;color:#c2410c}
.dl-pill-si{background:#f0fdf4;color:#166534}
.dl-pill-other{background:#f3f4f6;color:#4b5563;border:1px solid #e5e7eb}
		`;
		document.head.appendChild(s);
	}

	/* ── Layout ──────────────────────────────────────────────── */
	_renderLayout() {
		$(this.wrapper).find(".layout-main-section").html(`
<div class="dl-wrap">
  <div class="dl-filter-card">
    <div class="dl-fg">
      <label>Company</label>
      <select id="dl-co-sel"><option value="">Select company…</option></select>
    </div>
    <div class="dl-fg dl-fg-acc">
      <label>Account / Party</label>
      <div id="dl-sel-pill-wrap"></div>
      <input id="dl-acc-inp" type="text" placeholder="Type to search accounts, suppliers, customers…" autocomplete="off">
      <div class="dl-drop" id="dl-drop" style="display:none"></div>
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
      <button class="dl-btn dl-btn-secondary" id="dl-print-btn">Print</button>
    </div>
  </div>
  <div id="dl-area">
    <div class="dl-placeholder">Select a company and account / party, then click <strong>Show</strong>.</div>
  </div>
</div>
		`);
	}

	/* ── Events ──────────────────────────────────────────────── */
	_bindEvents() {
		var self = this;

		_gel("dl-co-sel").addEventListener("change", function () {
			self._clearSelection();
		});

		_gel("dl-acc-inp").addEventListener("input", _debounce(function () {
			var co  = _gel("dl-co-sel").value;
			var txt = this.value.trim();
			if (co && txt.length >= 2) self._search(co, txt);
			else _gel("dl-drop").style.display = "none";
		}, 280));

		_gel("dl-acc-inp").addEventListener("focus", function () {
			var co  = _gel("dl-co-sel").value;
			var txt = this.value.trim();
			if (co && txt.length >= 2) self._search(co, txt);
		});

		document.addEventListener("click", function (e) {
			if (!e.target.closest(".dl-fg-acc")) {
				_gel("dl-drop").style.display = "none";
			}
		});

		_gel("dl-show-btn").addEventListener("click",  function () { self.fetchReport(); });
		_gel("dl-print-btn").addEventListener("click", function () { self._printReport(); });

		["dl-co-sel", "dl-acc-inp", "dl-from", "dl-to"].forEach(function (id) {
			_gel(id).addEventListener("keydown", function (ev) {
				if (ev.key === "Enter") self.fetchReport();
			});
		});
	}

	/* ── Default dates ───────────────────────────────────────── */
	_setDefaultDates() {
		var now = new Date();
		var m   = now.getMonth();
		var yr  = now.getFullYear();
		var fyStart = m >= 3 ? yr : yr - 1;
		_gel("dl-from").value = fyStart + "-04-01";
		_gel("dl-to").value   = now.toISOString().split("T")[0];
	}

	/* ── Load companies ──────────────────────────────────────── */
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
						filters: [["user","=",email],["allow","=","Company"]],
						fields: ["for_value"],
						limit_page_length: 200,
					},
					callback: function (r2) {
						var items = r2.message || [];
						if (items.length) {
							self._populateCompanies(items.map(function (p) { return p.for_value; }));
						} else {
							frappe.call({
								method: "frappe.client.get_list",
								args: {
									doctype: "Company",
									filters: [["is_group","=",0]],
									fields: ["name"],
									limit_page_length: 200,
									order_by: "name asc",
								},
								callback: function (r3) {
									self._populateCompanies((r3.message || []).map(function (c) { return c.name; }));
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

	/* ── Selection management ────────────────────────────────── */
	_clearSelection() {
		this._selected = null;
		_gel("dl-acc-inp").value = "";
		_gel("dl-sel-pill-wrap").innerHTML = "";
		_gel("dl-drop").style.display = "none";
	}

	_selectItem(item) {
		var self      = this;
		this._selected = item;
		_gel("dl-acc-inp").value     = "";
		_gel("dl-acc-inp").placeholder = "Selected ↑ — type to change";
		_gel("dl-drop").style.display = "none";

		var typeLabel = item.type === "party" ? item.party_type : item.meta.split("·")[0].trim();
		_gel("dl-sel-pill-wrap").innerHTML =
			`<div class="dl-sel-pill">
				${_esc(item.label)}
				<span class="dl-sel-pill-x" id="dl-clear-sel" title="Clear">×</span>
			</div>`;

		document.getElementById("dl-clear-sel").addEventListener("click", function () {
			self._clearSelection();
			_gel("dl-acc-inp").placeholder = "Type to search accounts, suppliers, customers…";
		});
	}

	/* ── Account / Party search ──────────────────────────────── */
	_search(company, txt) {
		var self = this;
		frappe.call({
			method: "dux_voucher.dux_voucher.api.reports_api.search_ledger",
			args: { company: company, search_txt: txt },
			callback: function (r) {
				var results = r.message || [];
				var drop = _gel("dl-drop");

				if (!results.length) {
					drop.innerHTML = '<div class="dl-drop-empty">No matches found</div>';
					drop.style.display = "block";
					return;
				}

				// Group by type
				var accounts = results.filter(function (x) { return x.type === "account"; });
				var parties  = results.filter(function (x) { return x.type === "party"; });
				var html     = "";

				if (accounts.length) {
					html += '<div class="dl-drop-section">Accounts</div>';
					html += accounts.map(function (item) {
						return `<div class="dl-drop-item" data-idx="${_esc(JSON.stringify(item))}">
							<span class="dl-drop-label">${_esc(item.label)}</span>
							<span class="dl-drop-meta">${_esc(item.meta)}</span>
						</div>`;
					}).join("");
				}
				if (parties.length) {
					html += '<div class="dl-drop-section">Parties</div>';
					html += parties.map(function (item) {
						return `<div class="dl-drop-item" data-idx="${_esc(JSON.stringify(item))}">
							<span class="dl-drop-label">${_esc(item.label)}</span>
							<span class="dl-drop-meta">${_esc(item.meta)}</span>
						</div>`;
					}).join("");
				}

				drop.innerHTML = html;
				drop.style.display = "block";

				drop.querySelectorAll(".dl-drop-item").forEach(function (el) {
					el.addEventListener("click", function () {
						var item = JSON.parse(el.dataset.idx);
						self._selectItem(item);
						self.fetchReport();
					});
				});
			},
		});
	}

	/* ── Route options ───────────────────────────────────────── */
	applyRouteOptions(opts) {
		if (opts.company)    _gel("dl-co-sel").value = opts.company;
		if (opts.account)    { _gel("dl-acc-inp").value = opts.account; }
		if (opts.from_date)  _gel("dl-from").value   = opts.from_date;
		if (opts.to_date)    _gel("dl-to").value     = opts.to_date;
		if (opts.company && opts.account) this.fetchReport();
	}

	/* ── Fetch report ────────────────────────────────────────── */
	fetchReport() {
		var company   = _gel("dl-co-sel").value;
		var from_date = _gel("dl-from").value;
		var to_date   = _gel("dl-to").value;

		// Resolve account and party from selection
		var account    = "";
		var party      = null;
		var party_type = null;

		if (this._selected) {
			if (this._selected.type === "account") {
				account = this._selected.value;
			} else {
				// party mode
				account    = this._selected.account;
				party      = this._selected.value;
				party_type = this._selected.party_type;
			}
		} else {
			// Fallback: use raw text input as account name
			account = _gel("dl-acc-inp").value.trim();
		}

		if (!company) { frappe.msgprint({message:"Please select a Company.",indicator:"orange"}); return; }
		if (!account) { frappe.msgprint({message:"Please select an Account or Party.",indicator:"orange"}); return; }
		if (!from_date || !to_date) { frappe.msgprint({message:"Please set both dates.",indicator:"orange"}); return; }

		_gel("dl-area").innerHTML = '<div class="dl-placeholder">Loading…</div>';
		_gel("dl-print-btn").style.display = "none";
		this._lastData = null;

		var self = this;
		var args = { company: company, account: account, from_date: from_date, to_date: to_date };
		if (party)      args.party      = party;
		if (party_type) args.party_type = party_type;

		frappe.call({
			method: "dux_voucher.dux_voucher.api.reports_api.get_ledger_statement",
			args: args,
			callback: function (r) {
				if (r.message) {
					self._lastData = r.message;
					self._render(r.message);
					_gel("dl-print-btn").style.display = "inline-block";
				} else {
					_gel("dl-area").innerHTML =
						'<div class="dl-placeholder">No data found for this selection and period.</div>';
				}
			},
			error: function () {
				_gel("dl-area").innerHTML =
					'<div class="dl-placeholder" style="color:#dc2626">Could not load report. Please verify the account name and try again.</div>';
			},
		});
	}

	/* ── Print in new clean window ───────────────────────────── */
	_printReport() {
		if (!this._lastData) return;
		var d   = this._lastData;
		var win = window.open("", "_blank", "width=1000,height=700");

		var tableRows = "";

		// Opening
		tableRows += `<tr class="ob-row">
			<td colspan="4" class="ob-label">Opening Balance</td>
			<td></td><td></td>
			<td class="bal-cell ${d.opening_type === 'Dr' ? 'dr' : 'cr'}">${_fmt(d.opening_balance)}<span class="suf">${d.opening_type}</span></td>
		</tr>`;

		d.rows.forEach(function (row) {
			var drHtml = row.debit  > 0 ? `<span class="dr">${_fmt(row.debit)}</span>`  : `<span class="nil">—</span>`;
			var crHtml = row.credit > 0 ? `<span class="cr">${_fmt(row.credit)}</span>` : `<span class="nil">—</span>`;
			var pClass = row.prefix === "To" ? "to-kw" : "by-kw";
			tableRows += `<tr>
				<td class="dt">${_esc(row.posting_date)}</td>
				<td><span class="${pClass}">${row.prefix}</span> ${_esc(row.contra)}</td>
				<td>${_esc(row.voucher_type)}</td>
				<td class="mono">${_esc(row.voucher_no)}</td>
				<td class="num">${drHtml}</td>
				<td class="num">${crHtml}</td>
				<td class="num bal-cell ${row.balance_type === 'Dr' ? 'dr' : 'cr'}">${_fmt(row.balance)}<span class="suf">${row.balance_type}</span></td>
			</tr>`;
			if (row.remarks) {
				tableRows += `<tr class="rmk-row"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
			}
		});

		// Closing
		tableRows += `<tr class="cb-row">
			<td colspan="4" class="ob-label">Closing Balance</td>
			<td></td><td></td>
			<td class="bal-cell ${d.closing_type === 'Dr' ? 'dr' : 'cr'}" style="font-size:13px;font-weight:700">${_fmt(d.closing_balance)}<span class="suf">${d.closing_type}</span></td>
		</tr>`;

		// Totals
		tableRows += `<tr class="tot-row">
			<td colspan="4" style="text-align:right;font-size:10px;text-transform:uppercase;letter-spacing:.07em;color:#888">Period Totals</td>
			<td class="num dr">${_fmt(d.total_debit)}</td>
			<td class="num cr">${_fmt(d.total_credit)}</td>
			<td></td>
		</tr>`;

		win.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Ledger Statement — ${_esc(d.account_name)}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:'Inter',Arial,sans-serif;background:#fff;color:#111827;font-size:12px;padding:32px 40px}
  
  .print-header{margin-bottom:24px;padding-bottom:16px;border-bottom:2px solid #111827}
  .print-co{font-size:18px;font-weight:700;color:#111827;margin-bottom:4px}
  .print-ledger{font-size:13px;font-weight:500;color:#374151;margin-bottom:3px;display:flex;align-items:center;gap:8px}
  .print-badge{font-size:10px;font-weight:700;background:#eff6ff;color:#1d4ed8;border-radius:3px;padding:1px 6px}
  .print-party-badge{font-size:10px;font-weight:700;background:#f0fdf4;color:#166534;border-radius:3px;padding:1px 6px}
  .print-period{font-size:11px;color:#6b7280;font-family:monospace}
  
  table{width:100%;border-collapse:collapse;margin-top:4px}
  thead th{
    font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;
    color:#6b7280;padding:7px 10px;background:#f9fafb;
    border-bottom:1px solid #e5e7eb;white-space:nowrap;
  }
  thead th.r{text-align:right}
  
  td{padding:7px 10px;border-bottom:1px solid #f3f4f6;vertical-align:top}
  tr:hover td{background:#fafbff}
  
  .ob-row td,.cb-row td{background:#f3f4f6;padding:8px 10px}
  .cb-row td{border-top:2px solid #d1d5db}
  .ob-label{font-weight:700;font-size:9px;text-transform:uppercase;letter-spacing:.08em;color:#374151}
  
  .tot-row td{border-top:2px solid #d1d5db;font-weight:700;padding:8px 10px}
  
  .rmk-row td{
    padding:1px 10px 7px 22px;border-bottom:1px solid #f3f4f6;
    font-size:10px;color:#9ca3af;font-style:italic;
  }
  
  .dt{color:#6b7280;font-family:monospace;font-size:11px;white-space:nowrap}
  .mono{font-family:monospace;font-size:11px;color:#2563eb}
  .num{text-align:right;font-family:monospace;white-space:nowrap}
  .nil{color:#d1d5db}
  .dr{color:#dc2626;font-weight:500}
  .cr{color:#059669;font-weight:500}
  .bal-cell{font-weight:700}
  .suf{font-size:8px;margin-left:2px;font-weight:700;opacity:.65}
  .to-kw{color:#2563eb;font-weight:700;font-size:11px;margin-right:3px}
  .by-kw{color:#059669;font-weight:700;font-size:11px;margin-right:3px}
  
  .print-footer{margin-top:24px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:10px;color:#9ca3af;text-align:center}
  
  @media print{
    body{padding:16px 24px}
    @page{margin:15mm 12mm;size:A4 landscape}
  }
</style>
</head>
<body>
<div class="print-header">
  <div class="print-co">${_esc(d.company)}</div>
  <div class="print-ledger">
    <span>Ledger:</span>
    <strong>${_esc(d.account_name)}</strong>
    <span class="${d.account_type === 'Customer' || d.account_type === 'Supplier' || d.account_type === 'Employee' ? 'print-party-badge' : 'print-badge'}">${_esc(d.account_type)}</span>
  </div>
  <div class="print-period">${_esc(d.from_date)}  →  ${_esc(d.to_date)}  ·  ${d.row_count} transaction${d.row_count !== 1 ? "s" : ""}</div>
</div>

<table>
  <thead>
    <tr>
      <th style="width:74px">Date</th>
      <th>Particulars</th>
      <th style="width:120px">Vch Type</th>
      <th style="width:130px">Vch No</th>
      <th class="r" style="width:100px">Debit</th>
      <th class="r" style="width:100px">Credit</th>
      <th class="r" style="width:110px">Balance</th>
    </tr>
  </thead>
  <tbody>${tableRows}</tbody>
</table>

<div class="print-footer">Printed on ${new Date().toLocaleDateString("en-IN", {day:"2-digit",month:"short",year:"numeric"})}  ·  Dux DigiTech  ·  Powered by Dux Voucher</div>
<script>window.onload=function(){window.print()}<\/script>
</body>
</html>`);
		win.document.close();
	}

	/* ── Render on-screen report ─────────────────────────────── */
	_render(d) {
		var rows = "";

		rows += `<tr class="dl-tr-ob">
			<td colspan="4"><span class="dl-ob-label">Opening Balance</span></td>
			<td class="dl-c-amt"></td><td class="dl-c-amt"></td>
			<td class="dl-c-bal">${_bal(d.opening_balance, d.opening_type)}</td>
		</tr>`;

		if (!d.rows.length) {
			rows += `<tr><td colspan="7" class="dl-placeholder" style="padding:32px">No transactions in this period.</td></tr>`;
		}

		d.rows.forEach(function (row) {
			var pCls  = row.prefix === "To" ? "dl-to" : "dl-by";
			var drHtml = row.debit  > 0 ? `<span class="dl-dr">${_fmt(row.debit)}</span>`  : `<span class="dl-nil">—</span>`;
			var crHtml = row.credit > 0 ? `<span class="dl-cr">${_fmt(row.credit)}</span>` : `<span class="dl-nil">—</span>`;

			rows += `<tr class="dl-tr-e">
				<td class="dl-c-date">${_esc(row.posting_date)}</td>
				<td class="dl-c-part"><span class="${pCls}">${row.prefix}</span><span class="dl-contra-name">${_esc(row.contra)}</span></td>
				<td class="dl-c-vt">${_pill(row.voucher_type)}</td>
				<td class="dl-c-vno"><a class="dl-vno" href="${_esc(row.voucher_url)}" target="_blank">${_esc(row.voucher_no)}</a></td>
				<td class="dl-c-amt">${drHtml}</td>
				<td class="dl-c-amt">${crHtml}</td>
				<td class="dl-c-bal">${_bal(row.balance, row.balance_type)}</td>
			</tr>`;

			if (row.remarks) {
				rows += `<tr class="dl-tr-r"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
			}
		});

		rows += `<tr class="dl-tr-cb">
			<td colspan="4"><span class="dl-cb-label">Closing Balance</span></td>
			<td class="dl-c-amt"></td><td class="dl-c-amt"></td>
			<td class="dl-c-bal" style="font-size:13px">${_bal(d.closing_balance, d.closing_type)}</td>
		</tr>`;

		rows += `<tr class="dl-tr-tot">
			<td colspan="4" class="dl-tot-label">Period Totals</td>
			<td class="dl-c-amt"><span class="dl-dr">${_fmt(d.total_debit)}</span></td>
			<td class="dl-c-amt"><span class="dl-cr">${_fmt(d.total_credit)}</span></td>
			<td class="dl-c-bal"></td>
		</tr>`;

		var badge = d.account_type
			? `<span class="${d.account_type === "Customer" || d.account_type === "Supplier" || d.account_type === "Employee" ? "dl-party-badge" : "dl-acc-type-badge"}">${_esc(d.account_type)}</span>`
			: "";

		_gel("dl-area").innerHTML = `
<div class="dl-report-card">
  <div class="dl-rpt-hdr">
    <div class="dl-rpt-co">${_esc(d.company)}</div>
    <div class="dl-rpt-ledger-row">
      <span>Ledger:</span><strong>${_esc(d.account_name)}</strong>${badge}
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

/* ── Utilities ────────────────────────────────────────────────── */
function _gel(id) { return document.getElementById(id); }

function _fmt(val) {
	return new Intl.NumberFormat("en-IN", {
		minimumFractionDigits: 2, maximumFractionDigits: 2,
	}).format(val || 0);
}

function _bal(val, type) {
	if (!val) return '<span style="color:#9ca3af;font-family:monospace">0.00</span>';
	var cls = type === "Dr" ? "dl-bal-dr" : "dl-bal-cr";
	return `<span class="${cls}">${_fmt(val)}<span class="dl-bsuf">${type}</span></span>`;
}

function _pill(vtype) {
	var map = {
		"Payment Voucher":  "dl-pill-pv",
		"Receipt Voucher":  "dl-pill-rv",
		"Journal Entry":    "dl-pill-jv",
		"Contra Entry":     "dl-pill-cv",
		"Payment Entry":    "dl-pill-pv",
		"Receipt Entry":    "dl-pill-rv",
		"Purchase Invoice": "dl-pill-pi",
		"Sales Invoice":    "dl-pill-si",
	};
	return `<span class="dl-pill ${map[vtype] || "dl-pill-other"}">${_esc(vtype)}</span>`;
}

function _esc(str) {
	if (str === null || str === undefined) return "";
	return String(str)
		.replace(/&/g, "&amp;").replace(/</g, "&lt;")
		.replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function _debounce(fn, ms) {
	var t;
	return function () {
		var ctx = this, args = arguments;
		clearTimeout(t);
		t = setTimeout(function () { fn.apply(ctx, args); }, ms);
	};
}
