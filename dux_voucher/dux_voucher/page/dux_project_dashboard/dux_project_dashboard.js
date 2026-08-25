/* ============================================================
   dux_project_dashboard.js  —  Capital Projects
   Dux DigiTech  —  dux_voucher app

   Executive view of project spend across the group. Every figure except
   Committed is computed from GL Entry, so it ties to the books; Committed
   comes from Purchase Orders, which post no ledger entries, and is
   labelled as a forecast.

   Backed by dux_voucher.dux_voucher.api.project_dashboard.

   Wrapped in an IIFE so the local helpers don't collide with the
   identically-named globals in the other Dux pages.
   ============================================================ */

(function () {

frappe.pages["dux-project-dashboard"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Capital Projects",
			single_column: true,
		});
		new DuxProjectDashboard(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
		);
		console.error("dux-project-dashboard:", e);
	}
};

function _esc(s) {
	return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
		return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
	});
}

/* Indian grouping — 1,25,00,000 not 12,500,000. */
function _num(v) {
	v = Math.round(Math.abs(Number(v) || 0));
	var s = String(v), last3 = s.slice(-3), rest = s.slice(0, -3);
	if (rest) last3 = rest.replace(/\B(?=(\d{2})+(?!\d))/g, ",") + "," + last3;
	return last3;
}

/* Compact form for the KPI tiles — crore / lakh, as an Indian CFO reads. */
function _short(v) {
	var n = Number(v) || 0, a = Math.abs(n), sign = n < 0 ? "-" : "";
	if (a >= 1e7) return sign + (a / 1e7).toFixed(2) + " Cr";
	if (a >= 1e5) return sign + (a / 1e5).toFixed(2) + " L";
	return sign + _num(a);
}

function _today() {
	var d = new Date();
	return d.toISOString().slice(0, 10);
}
function _monthsAgo(n) {
	var d = new Date();
	d.setMonth(d.getMonth() - n);
	return d.toISOString().slice(0, 10);
}

class DuxProjectDashboard {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.data = null;
		this._busy = false;

		this._injectStyles();
		this._renderShell();
		this.load();
	}

	get $() { return $(this.wrapper).find(".layout-main-section"); }

	_injectStyles() {
		if (document.getElementById("dpd-styles")) return;
		var s = document.createElement("style");
		s.id = "dpd-styles";
		s.textContent = `
.dpd{padding:18px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.dpd-mono{font-family:'SFMono-Regular',Consolas,monospace;font-variant-numeric:tabular-nums}
.dpd-card{background:#fff;border:1px solid #e8eaed;border-radius:12px;box-shadow:0 1px 2px rgba(16,24,40,.04)}
.dpd-lbl{font-size:10px;font-weight:700;color:#8b929e;text-transform:uppercase;letter-spacing:.09em}
.dpd-bar{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;margin-bottom:16px}
.dpd-fg{display:flex;flex-direction:column;gap:5px}
.dpd-fg label{font-size:10px;font-weight:700;color:#8b929e;text-transform:uppercase;letter-spacing:.08em}
.dpd-fg select,.dpd-fg input{height:34px;border:1px solid #e8eaed;border-radius:8px;padding:0 10px;font-size:12.5px;color:#111827;background:#fff;outline:none;font-family:inherit;box-sizing:border-box}
.dpd-fg select:focus,.dpd-fg input:focus{border-color:#0d9488;box-shadow:0 0 0 3px rgba(13,148,136,.08)}
.dpd-btn{height:34px;padding:0 15px;border-radius:8px;font-size:12.5px;font-weight:600;cursor:pointer;border:1px solid #e8eaed;background:#fff;color:#374151;font-family:inherit}
.dpd-btn:hover{background:#f9fafb}
.dpd-btn-p{background:#0d9488;border-color:#0d9488;color:#fff}
.dpd-btn-p:hover{background:#0f766e}
.dpd-kpis{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:12px;margin-bottom:14px}
.dpd-kpi{padding:15px 17px}
.dpd-kpi-v{font-size:23px;font-weight:700;letter-spacing:-.025em;line-height:1.15;margin-top:8px}
.dpd-kpi-cur{font-size:13px;font-weight:600;color:#8b929e;margin-right:2px}
.dpd-kpi-sub{font-size:11px;color:#8b929e;margin-top:8px;padding-top:8px;border-top:1px solid #f4f5f7;line-height:1.5}
.dpd-warn{border-color:#fde68a;background:linear-gradient(180deg,#fffdf7 0,#fff 42%)}
.dpd-warn .dpd-lbl,.dpd-warn .dpd-kpi-v{color:#92400e}
.dpd-warn .dpd-kpi-sub{color:#b45309;border-top-color:#fef3c7}
.dpd-bad{border-color:#fecaca;background:linear-gradient(180deg,#fffafa 0,#fff 42%)}
.dpd-bad .dpd-lbl,.dpd-bad .dpd-kpi-v{color:#b91c1c}
.dpd-bad .dpd-kpi-sub{color:#b91c1c;border-top-color:#fee2e2}
.dpd-grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.dpd-h{font-size:14px;font-weight:700;margin-bottom:2px}
.dpd-hs{font-size:11.5px;color:#8b929e}
.dpd-th{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#8b929e;padding:10px 14px;text-align:left;border-bottom:1px solid #eef0f2;background:#fff;white-space:nowrap}
.dpd-td{padding:12px 14px;border-bottom:1px solid #f4f5f7;vertical-align:middle}
.dpd-tr:hover .dpd-td{background:#f6fefb;cursor:pointer}
.dpd-pill{font-size:10px;font-weight:700;border-radius:5px;padding:3px 8px;letter-spacing:.03em;display:inline-block;white-space:nowrap}
.dpd-prog{height:7px;background:#f1f2f4;border-radius:4px;overflow:hidden;margin-bottom:4px}
.dpd-prog i{display:block;height:100%}
.dpd-empty{padding:56px 28px;text-align:center}
.dpd-empty-h{font-size:16px;font-weight:700;color:#111827;margin-bottom:8px}
.dpd-empty-p{font-size:13px;color:#6b7280;line-height:1.7;max-width:620px;margin:0 auto 6px}
.dpd-foot{margin-top:16px;font-size:11px;color:#8b929e;line-height:1.65}
.dpd-attn{border-top:1px solid #f4f5f7;padding:13px 18px;display:flex;gap:11px;align-items:flex-start}
.dpd-spin{padding:60px;text-align:center;color:#8b929e;font-size:13px}
@media (max-width:1200px){.dpd-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.dpd-grid{grid-template-columns:1fr}}
@media (max-width:760px){.dpd-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;
		document.head.appendChild(s);
	}

	_renderShell() {
		this.$.html(`
<div class="dpd">
  <div class="dpd-bar">
    <div class="dpd-fg">
      <label>From</label>
      <input type="date" id="dpd-from" value="${_monthsAgo(12)}">
    </div>
    <div class="dpd-fg">
      <label>To</label>
      <input type="date" id="dpd-to" value="${_today()}">
    </div>
    <div class="dpd-fg">
      <label>Status</label>
      <select id="dpd-status">
        <option value="All">All</option>
        <option value="Open">Open</option>
        <option value="Completed">Completed</option>
        <option value="On Hold">On hold</option>
        <option value="Cancelled">Cancelled</option>
      </select>
    </div>
    <button class="dpd-btn dpd-btn-p" id="dpd-go">Refresh</button>
    <div style="flex:1"></div>
    <div id="dpd-meta" style="font-size:11px;color:#8b929e;text-align:right;line-height:1.5"></div>
  </div>
  <div id="dpd-body"><div class="dpd-spin">Loading…</div></div>
</div>`);
		var self = this;
		this.$.find("#dpd-go").on("click", function () { self.load(); });
		this.$.find("#dpd-from, #dpd-to, #dpd-status").on("change", function () { self.load(); });
	}

	load() {
		if (this._busy) return;
		this._busy = true;
		var self = this;
		this.$.find("#dpd-body").html('<div class="dpd-spin">Loading…</div>');

		frappe.call({
			method: "dux_voucher.dux_voucher.api.project_dashboard.get_dashboard",
			args: {
				from_date: this.$.find("#dpd-from").val() || null,
				to_date: this.$.find("#dpd-to").val() || null,
				status: this.$.find("#dpd-status").val() || "All",
			},
			callback: function (r) {
				self._busy = false;
				if (!r || !r.message) return;
				self.data = r.message;
				self._render();
			},
			error: function () {
				self._busy = false;
				self.$.find("#dpd-body").html(
					'<div class="dpd-spin" style="color:#b91c1c">Could not load. See the error above.</div>');
			},
		});
	}

	_render() {
		var d = this.data, k = d.kpi;

		this.$.find("#dpd-meta").html(
			_esc(d.companies.length) + " of " + _esc(d.companies_permitted) + " companies hold projects<br>" +
			"as at " + _esc((d.generated_on || "").slice(0, 16))
		);

		var html = this._kpis(k);

		if (!k.total_projects) {
			html += `<div class="dpd-card dpd-empty">
  <div class="dpd-empty-h">No projects yet</div>
  <div class="dpd-empty-p">Create one from <b>New Project</b>, then tag spend to it.</div>
</div>`;
		} else if (!k.invoiced && !k.paid && !k.committed) {
			html += this._nothingTagged();
			html += this._projectTable(d.projects, true);
		} else {
			html += this._projectTable(d.projects, false);
			html += '<div class="dpd-grid">' + this._byCompany(d.by_company) +
				this._attention(d.attention) + "</div>";
		}

		html += `<div class="dpd-foot">
  Invoiced, Paid, Outstanding and Unattributed come from the ledger, so they tie to the books.
  <b style="color:#6b7280">Committed</b> is derived from Purchase Orders, which post no ledger entries &mdash;
  treat it as a forecast, not an accounting figure.
</div>`;

		this.$.find("#dpd-body").html(html);
		this._bindRows();
	}

	_kpis(k) {
		function tile(cls, label, value, sub) {
			return `<div class="dpd-card dpd-kpi ${cls}">
  <div class="dpd-lbl">${label}</div>
  <div class="dpd-kpi-v dpd-mono"><span class="dpd-kpi-cur">&#8377;</span>${value}</div>
  <div class="dpd-kpi-sub">${sub}</div>
</div>`;
		}
		return '<div class="dpd-kpis">' +
			tile("", "Committed", _short(k.committed), "Ordered, not yet invoiced") +
			tile("", "Invoiced", _short(k.invoiced),
				k.committed ? Math.round(k.invoiced / k.committed * 100) + "% of committed" : "Booked cost") +
			tile("", "Paid", _short(k.paid), "Cash actually out") +
			tile("dpd-warn", "Outstanding", _short(k.outstanding), "Invoiced, not yet paid") +
			tile(k.unattributed > 0 ? "dpd-bad" : "", "Unattributed", _short(k.unattributed),
				k.unattributed_entries ? _num(k.unattributed_entries) + " entries with no project"
									   : "Spend with no project tagged") +
			"</div>";
	}

	_nothingTagged() {
		return `<div class="dpd-card dpd-empty">
  <div class="dpd-empty-h">Nothing is tagged to a project yet</div>
  <div class="dpd-empty-p">
    The projects below exist, but no ledger entry, purchase order or invoice carries a project,
    so there is nothing to total.
  </div>
  <div class="dpd-empty-p" style="color:#8b929e">
    Spend starts appearing here as soon as the Project field is filled in on purchase orders,
    invoices and payment vouchers.
  </div>
</div>`;
	}

	_projectTable(rows, bare) {
		var body = rows.map(function (r) {
			var pct = r.pct_of_estimate;
			var barColor = pct == null ? "#e2e6ea" : (pct > 100 ? "#dc2626" : (pct > 85 ? "#f59e0b" : "#0d9488"));
			var barW = pct == null ? 0 : Math.min(100, pct);
			var pctText = pct == null ? "no estimate set"
				: (pct > 100 ? Math.round(pct) + "% &mdash; over estimate" : Math.round(pct) + "% of estimate");

			return `<tr class="dpd-tr" data-project="${_esc(r.name)}">
  <td class="dpd-td"><div style="font-weight:600;font-size:13px;color:#0d9488">${_esc(r.project_name)}</div>
      <div style="font-size:11px;color:#9ca3af" class="dpd-mono">${_esc(r.name)}</div></td>
  <td class="dpd-td"><span class="dpd-pill" style="background:#f4f5f7;color:#4b5563">${_esc(r.company)}</span></td>
  <td class="dpd-td"><span class="dpd-pill" style="background:${r.status === "Open" ? "#f0fdfa;color:#0f766e" : "#f4f5f7;color:#6b7280"}">${_esc(r.status)}</span></td>
  <td class="dpd-td dpd-mono" style="text-align:right;color:#8b929e">${r.estimated ? _num(r.estimated) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right">${r.committed ? _num(r.committed) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right">${r.invoiced ? _num(r.invoiced) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right">${r.paid ? _num(r.paid) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right;font-weight:700;color:${r.outstanding > 0 ? "#92400e" : "#c3c8d0"}">${r.outstanding ? _num(r.outstanding) : "&mdash;"}</td>
  <td class="dpd-td"><div class="dpd-prog"><i style="width:${barW}%;background:${barColor}"></i></div>
      <div style="font-size:10.5px;color:${pct > 100 ? "#b91c1c;font-weight:600" : "#8b929e"}" class="dpd-mono">${pctText}</div></td>
</tr>`;
		}).join("");

		return `<div class="dpd-card" style="overflow:hidden;margin-top:${bare ? 14 : 0}px">
  <div style="padding:16px 18px;border-bottom:1px solid #eef0f2">
    <div class="dpd-h">Projects by exposure</div>
    <div class="dpd-hs">${rows.length} project${rows.length === 1 ? "" : "s"} &nbsp;&middot;&nbsp; largest outstanding first</div>
  </div>
  <div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;min-width:1080px">
    <thead><tr>
      <th class="dpd-th">Project</th><th class="dpd-th" style="width:150px">Company</th>
      <th class="dpd-th" style="width:96px">Status</th>
      <th class="dpd-th" style="width:110px;text-align:right">Estimate</th>
      <th class="dpd-th" style="width:110px;text-align:right">Committed</th>
      <th class="dpd-th" style="width:110px;text-align:right">Invoiced</th>
      <th class="dpd-th" style="width:110px;text-align:right">Paid</th>
      <th class="dpd-th" style="width:118px;text-align:right">Outstanding</th>
      <th class="dpd-th" style="width:150px">Against estimate</th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table></div>
</div>`;
	}

	_byCompany(rows) {
		var max = Math.max.apply(null, rows.map(function (r) { return r.invoiced; }).concat([1]));
		var bars = rows.slice(0, 8).map(function (r) {
			var w = Math.max(2, Math.round(r.invoiced / max * 100));
			return `<div style="margin-bottom:12px">
  <div style="display:flex;justify-content:space-between;margin-bottom:5px">
    <span style="font-size:12px;color:#374151">${_esc(r.company)}</span>
    <span class="dpd-mono" style="font-size:12px;font-weight:600">&#8377;${_short(r.invoiced)}</span>
  </div>
  <div class="dpd-prog" style="height:8px"><i style="width:${w}%;background:#0d9488"></i></div>
</div>`;
		}).join("");

		return `<div class="dpd-card" style="padding:18px 20px">
  <div class="dpd-h">Spend by company</div>
  <div class="dpd-hs" style="margin-bottom:16px">Invoiced in this period</div>
  ${bars || '<div style="font-size:12.5px;color:#9ca3af">Nothing invoiced in this period.</div>'}
</div>`;
	}

	_attention(items) {
		var TONE = {
			"OVER":       "background:#fee2e2;color:#b91c1c",
			"UNTAGGED":   "background:#fee2e2;color:#b91c1c",
			"STALLED":    "background:#f4f5f7;color:#4b5563",
			"NOT BILLED": "background:#fef3c7;color:#b45309",
		};
		var rows = items.map(function (a) {
			return `<div class="dpd-attn">
  <span class="dpd-pill" style="${TONE[a.kind] || "background:#f4f5f7;color:#4b5563"};flex-shrink:0;margin-top:1px">${_esc(a.kind)}</span>
  <div style="flex:1">
    <div style="font-size:12.5px;color:#111827;font-weight:500">${_esc(a.title)}</div>
    <div style="font-size:11px;color:#8b929e;margin-top:2px">${_esc(a.detail)}</div>
  </div>
</div>`;
		}).join("");

		return `<div class="dpd-card" style="padding:0;overflow:hidden">
  <div style="padding:18px 20px 14px">
    <div class="dpd-h">Needs attention</div>
    <div class="dpd-hs">${items.length ? items.length + " item" + (items.length === 1 ? "" : "s") : "nothing flagged"}</div>
  </div>
  ${rows || '<div class="dpd-attn" style="color:#9ca3af;font-size:12.5px">Nothing over estimate, stalled or untagged.</div>'}
</div>`;
	}

	_bindRows() {
		var self = this;
		this.$.find(".dpd-tr").on("click", function () {
			var p = $(this).data("project");
			if (p) frappe.set_route("Form", "Project", p);
		});
	}
}

})();
