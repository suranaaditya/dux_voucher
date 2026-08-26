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

/* dd-mm-yyyy — an Indian accountant reads dates that way. */
function _date(iso) {
	if (!iso) return "";
	var p = String(iso).slice(0, 10).split("-");
	return p.length === 3 ? p[2] + "-" + p[1] + "-" + p[0] : iso;
}

/* Documents open beside the dashboard, not over it. */
function _openTab(href) {
	window.open(href, "_blank", "noopener");
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
		/* Empty means group-wide. The client's default view is the whole
		   group, so an untouched picker must not narrow anything. */
		this.companies = [];
		this.view = "portfolio";
		this.project = null;
		this.detail = null;

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
.dpd-co{position:relative;flex:0 1 320px;min-width:250px}
.dpd-chips{display:flex;flex-wrap:wrap;gap:5px;align-items:center;min-height:34px;
  border:1px solid #e8eaed;border-radius:8px;padding:3px 8px;background:#fff;cursor:text;box-sizing:border-box}
.dpd-chips:focus-within{border-color:#0d9488;box-shadow:0 0 0 3px rgba(13,148,136,.08)}
.dpd-chip{display:inline-flex;align-items:center;gap:6px;background:#f0fdfa;color:#0f766e;
  border-radius:6px;padding:2px 7px;font-size:11.5px;font-weight:600;max-width:170px}
.dpd-chip .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dpd-chip .x{cursor:pointer;opacity:.55;font-size:14px;line-height:1}
.dpd-chip .x:hover{opacity:1}
.dpd-chips input{border:0;outline:0;background:transparent;flex:1;min-width:70px;height:26px;
  font-size:12.5px;color:#111827;font-family:inherit}
.dpd-drop{position:absolute;top:calc(100% + 4px);left:0;right:0;z-index:50;background:#fff;
  border:1px solid #e8eaed;border-radius:10px;box-shadow:0 8px 24px rgba(16,24,40,.10);
  max-height:280px;overflow-y:auto;display:none}
.dpd-drop.open{display:block}
.dpd-opt{padding:9px 12px;cursor:pointer;font-size:12.5px;display:flex;justify-content:space-between;
  gap:10px;align-items:center}
.dpd-opt:hover{background:#f6fefb}
.dpd-opt .c{font-size:10.5px;color:#8b929e;white-space:nowrap}
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
/* ---- drill-down ---- */
.dpd-dhead{padding:2px 0 18px;border-bottom:1px solid #eef0f2;margin-bottom:18px}
.dpd-crumb{font-size:11.5px;margin-bottom:10px}
.dpd-crumb a{color:#8b929e;text-decoration:none}
.dpd-crumb a:hover{color:#0d9488}
.dpd-dhead-row{display:flex;justify-content:space-between;align-items:flex-start;gap:16px}
.dpd-dtitle{display:flex;align-items:center;gap:11px;margin-bottom:6px;flex-wrap:wrap;
  font-size:21px;font-weight:700;letter-spacing:-.02em}
.dpd-dmeta{font-size:12px;color:#8b929e}
.dpd-dperiod{font-size:11.5px;color:#9ca3af;margin-top:10px}
.dpd-dgrid{display:grid;gap:14px}
.dpd-dgrid-top{grid-template-columns:2fr 1fr;margin-bottom:14px}
.dpd-dgrid-charts{grid-template-columns:1fr 1fr;margin-bottom:14px;align-items:start}
.dpd-dgrid-bottom{grid-template-columns:1fr 1.35fr;align-items:start}
.dpd-stack{height:32px;background:#f1f2f4;border-radius:7px;overflow:hidden;display:flex;margin-bottom:12px}
.dpd-keys{display:flex;gap:20px;font-size:11.5px;color:#6b7280;flex-wrap:wrap}
.dpd-figs{display:grid;grid-template-columns:repeat(4,1fr);margin-top:22px;padding-top:18px;
  border-top:1px solid #f4f5f7}
.dpd-dfig{font-size:17px;font-weight:700}
.dpd-step{display:flex;gap:13px}
.dpd-rail{display:flex;flex-direction:column;align-items:center}
.dpd-rail i{width:9px;height:9px;border-radius:5px;margin-top:5px;flex-shrink:0}
.dpd-line{width:2px;flex:1;background:#e2e6ea;min-height:26px}
.dpd-stepbody{flex:1;padding-bottom:16px}
.dpd-stepbody.last{padding-bottom:0}
.dpd-steprow{display:flex;justify-content:space-between;gap:10px}
.dpd-stepname{font-size:12.5px;font-weight:600;display:flex;align-items:center;gap:7px}
.dpd-stepval{font-size:12.5px;font-weight:700;white-space:nowrap}
.dpd-stepsub{font-size:11px;color:#8b929e;margin-top:2px;line-height:1.45}
.dpd-tag{font-size:9px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  color:#8b929e;background:#f4f5f7;border-radius:4px;padding:2px 5px}
.dpd-chead{padding:17px 20px 13px;display:flex;justify-content:space-between;align-items:center;gap:12px}
.dpd-total{font-weight:700;font-size:12.5px;border-bottom:none;border-top:2px solid #eef0f2}
.dpd-sub{font-size:11px;color:#8b929e;margin-top:2px}
.dpd-drow:hover .dpd-td{background:#f6fefb;cursor:pointer}
@media (max-width:1100px){.dpd-dgrid-top,.dpd-dgrid-charts,.dpd-dgrid-bottom{grid-template-columns:1fr}}
@media (max-width:640px){.dpd-figs{grid-template-columns:repeat(2,1fr);gap:14px}}
/* ---- who the money is with ---- */
.dpd-pstats{display:grid;grid-template-columns:repeat(5,1fr);gap:0;padding:0 20px 18px;
  border-bottom:1px solid #eef0f2}
.dpd-pstat-v{font-size:16px;font-weight:700;margin-top:5px}
.dpd-prow:hover .dpd-td{background:#f6fefb;cursor:pointer}
.dpd-prow.noco:hover .dpd-td{background:#fafafa;cursor:default}
.dpd-bridge{padding:12px 20px;font-size:11.5px;color:#8b929e;line-height:1.6}
.dpd-donut-wrap{display:flex;gap:18px;align-items:center;padding:4px 20px 20px;flex-wrap:wrap}
.dpd-donut{position:relative;width:132px;height:132px;flex-shrink:0}
.dpd-donut-mid{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:2px;pointer-events:none}
.dpd-legend{flex:1;min-width:190px;display:flex;flex-direction:column;gap:2px}
.dpd-leg{display:flex;align-items:center;gap:8px;font-size:12px;padding:4px 6px;border-radius:6px;cursor:pointer}
.dpd-leg:hover{background:#f6fefb}
.dpd-dot{width:9px;height:9px;border-radius:2px;flex-shrink:0}
.dpd-leg-n{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#374151}
.dpd-leg-v{font-weight:600;white-space:nowrap}
.dpd-leg-p{color:#9ca3af;width:34px;text-align:right;white-space:nowrap}
.dpd-bars{padding:4px 20px 20px;display:flex;flex-direction:column;gap:11px}
.dpd-barrow{cursor:pointer;border-radius:6px;padding:3px 6px;margin:-3px -6px}
.dpd-barrow:hover{background:#f6fefb}
.dpd-barhead{display:flex;justify-content:space-between;gap:10px;margin-bottom:5px}
.dpd-bar-n{font-size:12px;color:#374151;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dpd-bar-v{font-size:12px;font-weight:600;white-space:nowrap}
@media (max-width:900px){.dpd-pstats{grid-template-columns:repeat(3,1fr);gap:14px}}
@media (max-width:560px){.dpd-pstats{grid-template-columns:repeat(2,1fr)}}
.dpd-basis{margin-top:12px;padding:11px 15px;background:#f8fafb;border:1px solid #eef0f2;
  border-radius:9px;font-size:11.5px;color:#6b7280;line-height:1.65}
.dpd-basis b{color:#374151}
.dpd-figs-5{grid-template-columns:repeat(5,1fr)}
.dpd-ctot{text-align:right;flex-shrink:0}
.dpd-ctot-v{font-size:15px;font-weight:700;margin-top:4px;white-space:nowrap}
/* donut hover */
.dpd-donut svg circle{transition:opacity .12s,stroke-width .12s;cursor:pointer}
.dpd-donut.hot svg circle{opacity:.32}
.dpd-donut.hot svg circle.on{opacity:1;stroke-width:24}
.dpd-leg.on{background:#f0fdfa}
.dpd-tip{position:fixed;z-index:1000;pointer-events:none;background:#111827;color:#fff;
  border-radius:8px;padding:8px 11px;font-size:11.5px;line-height:1.5;
  box-shadow:0 6px 20px rgba(16,24,40,.22);white-space:nowrap;opacity:0;transition:opacity .1s}
.dpd-tip.show{opacity:1}
.dpd-tip .t{font-weight:700;margin-bottom:2px}
.dpd-tip .v{font-family:'SFMono-Regular',Consolas,monospace;font-variant-numeric:tabular-nums}
.dpd-tip .p{color:#9ca3af;margin-left:6px}
@media (max-width:900px){.dpd-figs-5{grid-template-columns:repeat(3,1fr);gap:14px}}
.dpd-wobar{height:6px;background:#f1f2f4;border-radius:3px;overflow:hidden;margin-top:5px;width:110px}
.dpd-wobar i{display:block;height:100%}
.dpd-worow:hover .dpd-td{background:#f6fefb;cursor:pointer}
.dpd-supline{display:flex;align-items:baseline;gap:12px;padding:5px 0;flex-wrap:wrap}
.dpd-supname{font-size:12px;font-weight:600;color:#374151;min-width:170px}
.dpd-supinv{flex:1;min-width:150px}
.dpd-supval{font-size:12.5px;font-weight:700;white-space:nowrap;margin-left:auto}
.dpd-loose{border-top:1px solid #eef0f2;padding:14px 20px;display:flex;gap:13px;align-items:flex-start}
.dpd-loose-v{font-size:15px;font-weight:700}
.dpd-loose-l{font-size:12.5px;font-weight:600;color:#111827}
.dpd-loose-s{font-size:11px;color:#8b929e;margin-top:3px;line-height:1.55}
.dpd-inv{display:inline-block;font-size:11px;margin-right:10px;color:#0d9488;cursor:pointer;
  font-family:'SFMono-Regular',Consolas,monospace}
.dpd-inv:hover{text-decoration:underline}
@media (max-width:1200px){.dpd-kpis{grid-template-columns:repeat(3,minmax(0,1fr))}.dpd-grid{grid-template-columns:1fr}}
@media (max-width:760px){.dpd-kpis{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;
		document.head.appendChild(s);
	}

	_renderShell() {
		this.$.html(`
<div class="dpd">
  <div class="dpd-bar">
    <div class="dpd-fg dpd-co">
      <label>Companies</label>
      <div class="dpd-chips" id="dpd-chips">
        <input id="dpd-co-inp" placeholder="All companies" autocomplete="off">
      </div>
      <div class="dpd-drop" id="dpd-drop"></div>
    </div>
    <div class="dpd-fg">
      <label title="Only changes which documents count as recent activity">Activity from</label>
      <input type="date" id="dpd-from" value="${_monthsAgo(12)}">
    </div>
    <div class="dpd-fg">
      <label title="Every cumulative figure is stated as at this date">As at</label>
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
		this._bindCompanyPicker();
	}

	/* ---- company picker -------------------------------------------
	   Chips, not a <select multiple>: the group runs to 69 companies and
	   a native multi-select gives no way to see what is currently on
	   without scrolling it. Same pattern as the Trial Balance page. */
	_bindCompanyPicker() {
		var self = this, $w = this.$, t = null;

		$w.on("click", "#dpd-chips", function () { $w.find("#dpd-co-inp").focus(); });

		$w.on("input", "#dpd-co-inp", function (e) {
			clearTimeout(t);
			var txt = e.target.value;
			t = setTimeout(function () { self._searchCompanies(txt); }, 180);
		});
		$w.on("focus", "#dpd-co-inp", function () {
			self._searchCompanies($w.find("#dpd-co-inp").val());
		});

		/* Namespaced so re-entering the page does not stack handlers. */
		$(document).off("click.dpd").on("click.dpd", function (e) {
			if (!$(e.target).closest(".dpd-co").length) $w.find("#dpd-drop").removeClass("open");
		});

		$w.on("click", ".dpd-opt[data-v]", function () {
			var v = $(this).attr("data-v");
			if (self.companies.indexOf(v) === -1) self.companies.push(v);
			$w.find("#dpd-co-inp").val("");
			$w.find("#dpd-drop").removeClass("open");
			self._renderChips();
			self.load();
		});

		$w.on("click", ".dpd-chip .x", function (e) {
			e.stopPropagation();
			var v = $(this).closest(".dpd-chip").attr("data-v");
			self.companies = self.companies.filter(function (c) { return c !== v; });
			self._renderChips();
			self.load();
		});
	}

	_searchCompanies(txt) {
		var self = this;
		frappe.call({
			method: "dux_voucher.dux_voucher.api.project_dashboard.search_companies",
			args: { txt: txt || "" },
			callback: function (r) {
				var rows = (r && r.message) || [];
				var picked = self.companies;
				var open = rows.filter(function (o) { return picked.indexOf(o.value) === -1; });
				var $d = self.$.find("#dpd-drop");

				if (!open.length) {
					$d.html('<div class="dpd-opt" style="color:#9ca3af;cursor:default">' +
						(rows.length ? "All matching companies are already selected"
									 : "No company with a project matches") + "</div>");
				} else {
					$d.html(open.map(function (o) {
						return '<div class="dpd-opt" data-v="' + _esc(o.value) + '">' +
							"<span>" + _esc(o.value) + "</span>" +
							'<span class="c">' + o.projects + " project" + (o.projects === 1 ? "" : "s") +
							"</span></div>";
					}).join(""));
				}
				$d.addClass("open");
			},
		});
	}

	_renderChips() {
		var $c = this.$.find("#dpd-chips");
		$c.find(".dpd-chip").remove();
		$c.prepend(this.companies.map(function (v) {
			return '<span class="dpd-chip" data-v="' + _esc(v) + '"><span class="n">' +
				_esc(v) + '</span><span class="x">&times;</span></span>';
		}).join(""));
		this.$.find("#dpd-co-inp").attr(
			"placeholder", this.companies.length ? "Add another…" : "All companies");
	}

	load() {
		/* The dates apply to both views; re-running while drilled in
		   should re-range the project, not throw you back to the list. */
		if (this.view === "detail" && this.project) {
			this.openProject(this.project);
			return;
		}
		if (this._busy) return;
		this._busy = true;
		var self = this;
		this.$.find("#dpd-body").html('<div class="dpd-spin">Loading…</div>');

		frappe.call({
			method: "dux_voucher.dux_voucher.api.project_dashboard.get_dashboard",
			args: {
				companies: this.companies,
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
			(d.scoped
				? _esc(d.companies_searched) + " of " + _esc(d.companies_permitted) +
				  " companies selected"
				: _esc(d.companies.length) + " of " + _esc(d.companies_permitted) +
				  " companies hold projects") +
			"<br>as at " + _esc((d.generated_on || "").slice(0, 16))
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
			if (d.parties && d.parties.length) {
				html += '<div style="margin-top:14px">' +
					this._partyCard(
						{ rows: d.parties, totals: d.party_totals },
						{ showCompany: true, total: d.parties_total }) + "</div>";
			}
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
		var asAt = _date(this.$.find("#dpd-to").val());
		return '<div class="dpd-kpis">' +
			tile("", "Committed (PO + WO)", _short(k.committed),
				"Purchase and work orders issued") +
			tile("", "Invoiced", _short(k.invoiced),
				k.committed ? Math.round(k.invoiced / k.committed * 100) + "% of committed" : "Booked cost") +
			tile("", "Paid", _short(k.paid),
				k.period_paid && Math.round(k.period_paid) !== Math.round(k.paid)
					? "&#8377;" + _short(k.period_paid) + " of it in this window"
					: "Cash actually out") +
			tile("dpd-warn", "Outstanding", _short(k.outstanding), "Invoiced, not yet paid") +
			tile(k.unattributed > 0 ? "dpd-bad" : "", "Unattributed", _short(k.unattributed),
				k.unattributed_entries ? _num(k.unattributed_entries) + " entries with no project"
									   : "Spend with no project tagged") +
			"</div>" +
			`<div class="dpd-basis">
  Every figure above is <b>project to date</b>, as at ${asAt} &mdash; not just the activity window.
  In the window shown: <b class="dpd-mono">&#8377;${_short(k.period_invoiced)}</b> invoiced,
  <b class="dpd-mono">&#8377;${_short(k.period_paid)}</b> paid.
</div>`;
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
      <th class="dpd-th" style="width:118px;text-align:right">Committed<br><span style="font-weight:600;letter-spacing:.02em;text-transform:none">PO + WO</span></th>
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
			var p = $(this).attr("data-project");
			if (p) self.openProject(p);
		});

		var d = this.data;
		if (d && d.parties && d.parties.length) {
			this._partyIndex = {};
			d.parties.forEach(function (r) { self._partyIndex[r.party] = r; });
			/* No fallback company here: the portfolio can span several, and
			   a party that works for two cannot be opened unambiguously. */
			this._bindParties(this.$, d.period, null);
		}
	}

	/* ================================================================
	   Drill-down — one project

	   Opened by clicking a row. The portfolio payload is kept in
	   this.data, so coming back is a re-render rather than a re-query.
	   ================================================================ */

	openProject(name) {
		var self = this;
		this.view = "detail";
		this.project = name;
		this._chrome();
		this.$.find("#dpd-body").html('<div class="dpd-spin">Loading…</div>');

		frappe.call({
			method: "dux_voucher.dux_voucher.api.project_dashboard.get_project_detail",
			args: {
				project: name,
				from_date: this.$.find("#dpd-from").val() || null,
				to_date: this.$.find("#dpd-to").val() || null,
			},
			callback: function (r) {
				if (!r || !r.message) return;
				self.detail = r.message;
				self._renderDetail();
			},
			error: function () {
				self.$.find("#dpd-body").html(
					'<div class="dpd-spin" style="color:#b91c1c">Could not open this project. See the error above.</div>');
			},
		});
	}

	backToPortfolio() {
		this.view = "portfolio";
		this.project = null;
		this._chrome();
		if (this.data) this._render(); else this.load();
	}

	/* Companies and Status belong to the portfolio; the dates still apply
	   to a single project, so they stay. */
	_chrome() {
		var detail = this.view === "detail";
		this.$.find(".dpd-co, #dpd-status").closest(".dpd-fg").toggle(!detail);
		this.$.find("#dpd-meta").toggle(!detail);
	}

	_renderDetail() {
		var d = this.detail, p = d.project, t = d.totals;

		this.$.find("#dpd-body").html(
			this._detailHead(p, d.period) +
			'<div class="dpd-dgrid dpd-dgrid-top">' +
				this._estimateCard(t) +
				this._chainCard(d.chain) +
			"</div>" +
			'<div class="dpd-dgrid dpd-dgrid-charts">' +
				this._donutCard(d.parties.work_orders, "Work orders by contractor",
					"Contract value, from the work orders") +
				this._barsCard(d.parties.purchase_orders, "Purchase orders by supplier",
					"Order value, from the purchase orders") +
			"</div>" +
			(d.work_orders
				? '<div style="margin-bottom:14px">' +
				  this._workOrderCard(d.work_orders, t.invoiced) + "</div>"
				: "") +
			'<div style="margin-bottom:14px">' +
				this._partyCard(d.parties, { limit: 25 }) + "</div>" +
			'<div class="dpd-dgrid dpd-dgrid-bottom">' +
				this._accountsCard(d.accounts, t.invoiced) +
				this._recentCard(d) +
			"</div>" +
			`<div class="dpd-foot">
  Invoiced and Paid are the ledger's own totals for this project, so they tie to the books and to
  the figures on the portfolio. <b style="color:#6b7280">Work Orders</b> and
  <b style="color:#6b7280">Purchase Orders</b> post no ledger entries at all &mdash; those two rows
  are read from the documents and are a forecast of what is still to come.
</div>`);

		this._bindDetail();
	}

	_detailHead(p, period) {
		var when = [];
		if (p.expected_start_date) when.push(_date(p.expected_start_date));
		if (p.expected_end_date) when.push(_date(p.expected_end_date));

		return `<div class="dpd-dhead">
  <div class="dpd-crumb"><a href="#" id="dpd-back">&lsaquo;&nbsp; Capital Projects</a></div>
  <div class="dpd-dhead-row">
    <div>
      <div class="dpd-dtitle">
        <span>${_esc(p.project_name)}</span>
        <span class="dpd-pill" style="background:${p.status === "Open" ? "#f0fdfa;color:#0f766e" : "#f4f5f7;color:#6b7280"}">${_esc(p.status)}</span>
        ${p.project_type ? '<span class="dpd-pill" style="background:#f4f5f7;color:#4b5563">' + _esc(p.project_type) + "</span>" : ""}
      </div>
      <div class="dpd-dmeta dpd-mono">${_esc(p.name)} &nbsp;&middot;&nbsp; ${_esc(p.company)}${
			when.length ? " &nbsp;&middot;&nbsp; " + when.join(" &rarr; ") : ""}</div>
    </div>
    <button class="dpd-btn" id="dpd-open-erp">Open in ERPNext</button>
  </div>
  <div class="dpd-dperiod">Money figures are project to date, as at ${_date(period.to_date)}.
    Recent activity is what moved since ${_date(period.from_date)}.</div>
</div>`;
	}

	/* ---- against estimate ------------------------------------------
	   Four stacked segments over whichever is larger, the estimate or
	   what has actually been committed — so a project that has run past
	   its estimate still renders a full bar instead of overflowing. */
	_estimateCard(t) {
		var uninvoiced = Math.max(0, t.uninvoiced);
		var spent = t.paid + t.outstanding + uninvoiced;
		var base = Math.max(t.estimated, spent, 1);
		var remaining = Math.max(0, base - spent);

		function seg(v, bg, fg, label) {
			var w = v / base * 100;
			if (w <= 0.05) return "";
			// Only caption a band wide enough to hold the words.
			var text = w >= 17 && label ? label : "";
			return '<div style="width:' + w + "%;background:" + bg +
				';height:100%;display:flex;align-items:center;padding-left:' +
				(text ? "12px" : "0") + ";color:" + fg +
				';font-size:11.5px;font-weight:600;white-space:nowrap;overflow:hidden">' +
				text + "</div>";
		}
		function key(bg, label) {
			return '<span style="display:flex;align-items:center;gap:6px">' +
				'<span style="width:9px;height:9px;border-radius:2px;background:' + bg + '"></span>' +
				label + "</span>";
		}
		function fig(label, value, tone) {
			return '<div><div class="dpd-lbl" style="margin-bottom:6px' +
				(tone ? ";color:" + tone : "") + '">' + label + "</div>" +
				'<div class="dpd-mono dpd-dfig"' + (tone ? ' style="color:' + tone + '"' : "") + ">" +
				(value ? _num(value) : "&mdash;") + "</div></div>";
		}

		var P = this.detail.period_totals || {};
		var period = (P.invoiced || P.paid)
			? `<div class="dpd-basis" style="margin:14px -22px -20px;border-radius:0 0 12px 12px">
  Figures are <b>project to date</b>. Of that, <b class="dpd-mono">&#8377;${_short(P.invoiced)}</b> was
  invoiced and <b class="dpd-mono">&#8377;${_short(P.paid)}</b> paid inside the activity window
  &mdash; ${P.documents} document${P.documents === 1 ? "" : "s"}.
</div>`
			: `<div class="dpd-basis" style="margin:14px -22px -20px;border-radius:0 0 12px 12px">
  Figures are <b>project to date</b>. Nothing moved inside the activity window.
</div>`;

		var pct = t.pct_of_estimate;
		var head = t.estimated
			? '<b style="color:' + (pct > 100 ? "#b91c1c" : "#374151") + ';font-size:13px">' +
			  Math.round(pct) + "%</b> committed" + (pct > 100 ? " &mdash; over estimate" : "")
			: '<span style="color:#9ca3af">no estimate set</span>';

		return `<div class="dpd-card" style="padding:20px 22px">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:16px">
    <div class="dpd-lbl">Against estimate</div>
    <div style="font-size:12px;color:#8b929e">${head}</div>
  </div>
  <div class="dpd-stack">
    ${seg(t.paid, "#0d9488", "#fff", "Paid &nbsp;&#8377;" + _short(t.paid))}
    ${seg(t.outstanding, "#2dd4bf", "#0f766e", "&#8377;" + _short(t.outstanding))}
    ${seg(uninvoiced, "#ccfbf1", "#0f766e", "&#8377;" + _short(uninvoiced))}
    ${seg(remaining, "#f1f2f4", "#8b929e", "")}
  </div>
  <div class="dpd-keys">
    ${key("#0d9488", "Paid")}
    ${key("#2dd4bf", "Invoiced, unpaid")}
    ${key("#ccfbf1", "Ordered, uninvoiced")}
    ${t.estimated ? key("#f1f2f4", "Estimate remaining") : ""}
  </div>
  <div class="dpd-figs dpd-figs-5">
    ${fig("Estimate", t.estimated, "#6b7280")}
    ${fig("Committed &middot; PO + WO", t.committed)}
    ${fig("Invoiced", t.invoiced)}
    ${fig("Paid to date", t.paid, "#0f766e")}
    ${fig(t.outstanding < 0 ? "Paid ahead" : "Outstanding",
		Math.abs(t.outstanding), t.outstanding < 0 ? "#1d4ed8" : "#92400e")}
  </div>
  ${period}
</div>`;
	}

	/* ---- the chain -------------------------------------------------- */
	_chainCard(chain) {
		var DOT = ["#0d9488", "#0d9488", "#2dd4bf", "#99f6e4"];

		var rows = chain.map(function (c, i) {
			var last = i === chain.length - 1;
			var caption = [];
			if (c.source === "document" && c.count) {
				caption.push(c.count + " " +
					(c.stage === "Work Orders" ? "contract" : "order") + (c.count === 1 ? "" : "s"));
			}
			/* A ledger stage's detail already counts its own documents —
			   "12 invoices · 4 journals" — so prefixing "16 vouchers"
			   only says it twice. */
			if (c.detail) caption.push(c.detail);

			return `<div class="dpd-step">
  <div class="dpd-rail">
    <i style="background:${DOT[i] || "#99f6e4"}"></i>
    ${last ? "" : '<span class="dpd-line"></span>'}
  </div>
  <div class="dpd-stepbody${last ? " last" : ""}">
    <div class="dpd-steprow">
      <span class="dpd-stepname">${_esc(c.stage)}${
		c.source === "document" ? '<span class="dpd-tag">forecast</span>' : ""}</span>
      <span class="dpd-mono dpd-stepval">${c.value ? "&#8377;" + _short(c.value) : "&mdash;"}</span>
    </div>
    <div class="dpd-stepsub">${caption.length ? _esc(caption.join("  ·  ")) : "nothing yet"}</div>
  </div>
</div>`;
		}).join("");

		return `<div class="dpd-card" style="padding:20px 22px">
  <div class="dpd-lbl" style="margin-bottom:16px">The chain</div>
  ${rows}
</div>`;
	}

	/* ---- where it went ---------------------------------------------- */
	_accountsCard(accounts, invoiced) {
		if (!accounts.length) {
			return `<div class="dpd-card" style="overflow:hidden">
  ${this._cardHead("Where it went", "Account-wise, from the ledger")}
  <div style="padding:28px 20px;font-size:12.5px;color:#9ca3af;text-align:center">
    No cost has been booked against this project in this period.</div>
</div>`;
		}

		var body = accounts.map(function (a) {
			return `<tr><td class="dpd-td" style="font-size:12.5px">${_esc(a.account)}</td>
  <td class="dpd-td dpd-mono" style="text-align:right;font-weight:600">${_num(a.amount)}</td></tr>`;
		}).join("");

		return `<div class="dpd-card" style="overflow:hidden">
  ${this._cardHead("Where it went", "Account-wise, from the ledger")}
  <table style="width:100%;border-collapse:collapse">
    <thead><tr><th class="dpd-th">Account</th>
      <th class="dpd-th" style="text-align:right;width:140px">Amount</th></tr></thead>
    <tbody>${body}
      <tr><td class="dpd-td dpd-total">Total invoiced</td>
          <td class="dpd-td dpd-mono dpd-total" style="text-align:right">${_num(invoiced)}</td></tr>
    </tbody>
  </table>
</div>`;
	}

	/* ---- recent documents ------------------------------------------- */
	_recentCard(d) {
		var TONE = {
			"Payment":  "background:#f0fdfa;color:#0f766e",
			"Receipt":  "background:#f0fdfa;color:#0f766e",
			"Refund":   "background:#fef3c7;color:#b45309",
			"Writeoff": "background:#fee2e2;color:#b91c1c",
		};

		if (!d.recent.length) {
			return `<div class="dpd-card" style="overflow:hidden">
  ${this._cardHead("Recent activity", "Every document touching this project")}
  <div style="padding:28px 20px;font-size:12.5px;color:#9ca3af;text-align:center">
    Nothing has been posted against this project in this period.</div>
</div>`;
		}

		/* Recent, not exhaustive: a long list pushes the summary above it
		   off the screen, which is the part worth reading first. The rest
		   are one click away in the ledger. */
		var shown = d.recent.slice(0, 12);

		var body = shown.map(function (r) {
			// One amount column: what this voucher did to the project. The
			// pill says which side that was, so the number is never ambiguous.
			var isCost = Math.abs(r.cost) > 0.005;
			var amount = isCost ? r.cost : r.paid;
			var caption = isCost
				? (Math.abs(r.paid) > 0.005 ? "cost · also &#8377;" + _short(r.paid) + " paid" : "cost")
				: "paid";
			var sub = r.party || r.remark || "";

			return `<tr class="dpd-drow" data-doctype="${_esc(r.doctype)}" data-name="${_esc(r.name)}">
  <td class="dpd-td dpd-mono" style="font-size:12px;color:#8b929e;white-space:nowrap">${_date(r.posting_date)}</td>
  <td class="dpd-td"><span class="dpd-pill" style="${TONE[r.kind] || "background:#f4f5f7;color:#4b5563"}">${_esc(r.kind)}</span></td>
  <td class="dpd-td">
    <span class="dpd-mono" style="font-size:12px;color:#0d9488;font-weight:600">${_esc(r.name)}</span>
    ${sub ? '<div class="dpd-sub">' + _esc(sub) + "</div>" : ""}
  </td>
  <td class="dpd-td dpd-mono" style="text-align:right;white-space:nowrap">
    <div style="font-weight:600">${_num(amount)}</div>
    <div style="font-size:10.5px;color:#9ca3af;margin-top:2px">${caption}</div>
  </td>
</tr>`;
		}).join("");

		var more = d.recent_total > shown.length
			? `<tr><td class="dpd-td" colspan="4" style="text-align:center;border-bottom:none;padding:12px">
   <a href="#" id="dpd-all" style="font-size:12px;font-weight:600;color:#0d9488">All ${_num(d.recent_total)} documents</a></td></tr>`
			: "";

		return `<div class="dpd-card" style="overflow:hidden">
  ${this._cardHead("Recent activity", d.recent_total + " document" + (d.recent_total === 1 ? "" : "s") +
		" touching this project", '<a href="#" id="dpd-gl" style="font-size:12px;font-weight:600;color:#0d9488">View ledger</a>')}
  <div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;min-width:520px">
    <thead><tr>
      <th class="dpd-th" style="width:96px">Date</th>
      <th class="dpd-th" style="width:96px">Type</th>
      <th class="dpd-th">Reference</th>
      <th class="dpd-th" style="text-align:right;width:140px">Amount</th>
    </tr></thead>
    <tbody>${body}${more}</tbody>
  </table></div>
</div>`;
	}

	/* ---- billing against each work order ---------------------------

	   The Raisoni process is Work Order -> Purchase Invoice, with no RA Bill
	   in between, so this reads straight off the invoice's own work-order
	   link. Ordered and billed are both pre-tax: Work Order Contract's
	   total_amount excludes tax, so billing is summed on base_net_amount —
	   a taxed bill against an untaxed order would show every contract
	   over-billed by its GST.

	   There is no Paid column on purpose. A payment settles a supplier's
	   payable, not a particular contract, and nothing in the ledger splits
	   cash across one contractor's several work orders. */
	_workOrderCard(W, invoicedTotal) {
		if (!W || !W.rows.length) return "";
		var t = W.totals;

		function stat(label, value, tone) {
			return '<div class="dpd-pstat"><div class="dpd-lbl"' +
				(tone ? ' style="color:' + tone + '"' : "") + ">" + label + "</div>" +
				'<div class="dpd-mono dpd-pstat-v"' + (tone ? ' style="color:' + tone + '"' : "") +
				">" + (value ? _num(value) : "&mdash;") + "</div></div>";
		}

		var body = W.rows.map(function (r) {
			var pct = r.pct == null ? 0 : Math.min(100, r.pct);
			var over = r.pct != null && r.pct > 100;
			return `<tr class="dpd-worow" data-wo="${_esc(r.name)}">
  <td class="dpd-td">
    <div class="dpd-mono" style="font-size:12px;font-weight:600;color:#0d9488">${_esc(r.name)}</div>
    ${r.title ? '<div class="dpd-sub">' + _esc(String(r.title).slice(0, 68)) + "</div>" : ""}
  </td>
  <td class="dpd-td" style="font-size:12.5px">${_esc(r.supplier)}</td>
  <td class="dpd-td dpd-mono" style="text-align:right">${r.ordered ? _num(r.ordered) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right;font-weight:${r.billed ? 600 : 400};color:${r.billed ? "#111827" : "#c3c8d0"}">${r.billed ? _num(r.billed) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right;font-weight:${r.balance ? 600 : 400};color:${r.balance > 0 ? "#92400e" : "#c3c8d0"}">${r.balance ? _num(r.balance) : "&mdash;"}</td>
  <td class="dpd-td">
    <div class="dpd-wobar"><i style="width:${pct}%;background:${over ? "#dc2626" : (r.billed ? "#0d9488" : "#e2e6ea")}"></i></div>
    <div class="dpd-mono" style="font-size:10.5px;color:${over ? "#b91c1c" : "#8b929e"};margin-top:3px">${
		r.billed ? Math.round(r.pct) + "% billed" + (over ? " &mdash; over" : "")
				 : "not billed yet"}</div>
  </td>
</tr>`;
		}).join("");

		/* Grouped by contractor, not just listed as invoice numbers. Whose
		   bills these are is the whole reason the figure differs from the
		   same contractor's Billed in the party table below. */
		function loose(kind, b, tone, label, note) {
			if (!b.count) return "";
			var shown = b.suppliers.slice(0, 6);
			var lines = shown.map(function (sup) {
				var links = sup.invoices.slice(0, 5).map(function (i) {
					return '<span class="dpd-inv" data-pi="' + _esc(i.name) + '">' + _esc(i.name) + "</span>";
				}).join("");
				var extra = sup.invoices.length - 5;
				return `<div class="dpd-supline">
  <div class="dpd-supname">${_esc(sup.supplier)}</div>
  <div class="dpd-supinv">${links}${extra > 0
		? '<span style="font-size:11px;color:#9ca3af">+' + extra + " more</span>" : ""}</div>
  <div class="dpd-mono dpd-supval">${_num(sup.value)}</div>
</div>`;
			}).join("");
			var restSup = b.suppliers.length - shown.length;

			return `<div class="dpd-loose">
  <div style="flex:1;min-width:0">
    <div style="display:flex;justify-content:space-between;gap:12px;align-items:baseline">
      <div class="dpd-loose-l" style="color:${tone}">${label}</div>
      <div class="dpd-mono dpd-loose-v" style="color:${tone};white-space:nowrap">${_num(b.value)}</div>
    </div>
    <div class="dpd-loose-s">${note}</div>
    <div style="margin-top:9px">${lines}${restSup > 0
		? '<div style="font-size:11px;color:#9ca3af;margin-top:6px">and ' + restSup +
		  " more contractor" + (restSup === 1 ? "" : "s") + "</div>" : ""}</div>
  </div>
</div>`;
		}

		var journals = invoicedTotal - W.invoice_total;

		return `<div class="dpd-card" style="overflow:hidden">
  ${this._cardHead("Work orders",
		W.rows.length + " contract" + (W.rows.length === 1 ? "" : "s") +
		" &nbsp;&middot;&nbsp; ordered against billed, from the invoices that name each one")}
  <div class="dpd-bridge" style="border-bottom:1px solid #eef0f2;padding-top:0">
    <b>Billed</b> here counts only invoices that name a work order. A contractor&rsquo;s total billing
    is in <b>Who the money is with</b> below &mdash; the difference is whatever sits in the two
    unlinked blocks at the foot of this card.
  </div>
  <div class="dpd-pstats" style="grid-template-columns:repeat(3,1fr)">
    ${stat("Ordered", t.ordered)}
    ${stat("Billed", t.billed)}
    ${stat("Left to bill", t.balance, "#92400e")}
  </div>
  <div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;min-width:760px">
    <thead><tr>
      <th class="dpd-th">Work order</th>
      <th class="dpd-th" style="width:180px">Contractor</th>
      <th class="dpd-th" style="text-align:right;width:120px">Ordered</th>
      <th class="dpd-th" style="text-align:right;width:120px">Billed</th>
      <th class="dpd-th" style="text-align:right;width:120px">Left to bill</th>
      <th class="dpd-th" style="width:130px">Progress</th>
    </tr></thead>
    <tbody>${body}</tbody>
  </table></div>
  ${loose("po", W.on_purchase_orders, "#4b5563", "Billed against purchase orders",
		"Material bought on a purchase order rather than a work order. Nothing to link.")}
  ${loose("loose", W.unattributed, "#b45309", "Not linked to anything",
		"On this project but naming neither a work order nor a purchase order. Someone still has to place these.")}
  ${Math.abs(journals) > 0.005 ? `<div class="dpd-bridge" style="border-top:1px solid #f4f5f7">
  A further <b class="dpd-mono">&#8377;${_num(journals)}</b> of cost reached this project through journals rather
  than purchase invoices, so it appears in Invoiced above but in none of these rows.
</div>` : ""}
</div>`;
	}

	/* ---- who the money is with -------------------------------------

	   Read off the PAYABLE side, not the cost side. A Purchase Invoice
	   debits CWIP with no party and credits the payable with one, so the
	   cost leg carries no party at all and cannot be split by contractor.

	   Owed and Advance are shown as two columns rather than one signed
	   balance: a project is routinely owed money on one contractor while
	   sitting ahead on another, and netting them hides whichever is
	   smaller. Advance is the one people ask for by name — cash out with
	   no bill against it. */
	_partyCard(P, opts) {
		var t = P.totals, rows = P.rows, self = this;
		if (!rows.length) {
			return `<div class="dpd-card" style="overflow:hidden">
  ${this._cardHead("Who the money is with", "Contractors and suppliers on this project")}
  <div style="padding:28px 20px;font-size:12.5px;color:#9ca3af;text-align:center">
    No contractor has been ordered from, billed or paid on this project yet.</div>
</div>`;
		}

		function stat(label, value, tone) {
			return '<div class="dpd-pstat"><div class="dpd-lbl"' +
				(tone ? ' style="color:' + tone + '"' : "") + ">" + label + "</div>" +
				'<div class="dpd-mono dpd-pstat-v"' + (tone ? ' style="color:' + tone + '"' : "") +
				">" + (value ? _num(value) : "&mdash;") + "</div></div>";
		}

		var shown = rows.slice(0, opts && opts.limit ? opts.limit : rows.length);
		var total = (opts && opts.total) || rows.length;
		var body = shown.map(function (r) {
			return `<tr class="dpd-prow${r.company ? "" : " noco"}"
     data-party="${_esc(r.party)}" data-ptype="${_esc(r.party_type)}"
     data-account="${_esc(r.account || "")}" data-company="${_esc(r.company || "")}">
  <td class="dpd-td">
    <div style="font-weight:600;font-size:12.5px;color:${r.company ? "#0d9488" : "#374151"}">${_esc(r.party)}</div>
    ${opts && opts.showCompany && r.company
		? '<div class="dpd-sub">' + _esc(r.company) + "</div>" : ""}
  </td>
  <td class="dpd-td dpd-mono" style="text-align:right">${r.ordered ? _num(r.ordered) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right">${r.billed ? _num(r.billed) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right">${r.paid ? _num(r.paid) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right;font-weight:${r.owed ? 700 : 400};color:${r.owed ? "#92400e" : "#c3c8d0"}">${r.owed ? _num(r.owed) : "&mdash;"}</td>
  <td class="dpd-td dpd-mono" style="text-align:right;font-weight:${r.advance ? 700 : 400};color:${r.advance ? "#1d4ed8" : "#c3c8d0"}">${r.advance ? _num(r.advance) : "&mdash;"}</td>
</tr>`;
		}).join("");

		var more = rows.length > shown.length
			? '<tr><td class="dpd-td" colspan="6" style="text-align:center;border-bottom:none;padding:11px;font-size:11.5px;color:#9ca3af">and ' +
			  _num(rows.length - shown.length) + " more with smaller balances</td></tr>"
			: "";

		/* The one number that stops this table reading as broken. */
		var bridge = t.cost_without_party > 0.005
			? `<div class="dpd-bridge">
  <b class="dpd-mono">&#8377;${_num(t.cost_without_party)}</b> of cost is booked to the project but never
  reached a contractor's payable, so it is in Invoiced above and in no row here. That happens when a
  voucher tags its expense line to the project and leaves the Creditors line untagged.
</div>` : "";

		return `<div class="dpd-card" style="overflow:hidden">
  ${this._cardHead("Who the money is with",
		(total > shown.length
			? "largest " + shown.length + " of " + total + " parties"
			: shown.length + " " + (shown.length === 1 ? "party" : "parties")) +
		" &nbsp;&middot;&nbsp; ordered, billed and settled &mdash; from the payable side of the ledger")}
  <div class="dpd-pstats">
    ${stat("Ordered", t.ordered)}
    ${stat("Billed", t.billed)}
    ${stat("Paid", t.paid)}
    ${stat("Still owed", t.owed, "#92400e")}
    ${stat("Advance paid", t.advance, "#1d4ed8")}
  </div>
  <div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;min-width:720px">
    <thead><tr>
      <th class="dpd-th">Party</th>
      <th class="dpd-th" style="text-align:right;width:120px">Ordered</th>
      <th class="dpd-th" style="text-align:right;width:120px">Billed</th>
      <th class="dpd-th" style="text-align:right;width:120px">Paid</th>
      <th class="dpd-th" style="text-align:right;width:120px">Still owed</th>
      <th class="dpd-th" style="text-align:right;width:130px">Advance paid</th>
    </tr></thead>
    <tbody>${body}${more}</tbody>
  </table></div>
  ${bridge}
  <div class="dpd-bridge" style="border-top:1px solid #f4f5f7;color:#9ca3af">
    <b style="color:#1d4ed8">Advance paid</b> is cash out with no bill against it &mdash; the payable
    has been debited for this party and never credited. Read off the ledger balance, not ERPNext's
    advance flag, so it catches payments made through any voucher type.
  </div>
</div>`;
	}

	/* ---- work orders: a donut ---------------------------------------
	   Five contractors, one of them most of the value — that reads well
	   as a donut. The purchase orders next to it do not, which is why
	   they get bars instead. */
	_donutCard(slices, title, sub) {
		if (!slices.length) {
			return `<div class="dpd-card" style="padding:0;overflow:hidden">
  ${this._cardHead(title, sub)}
  <div style="padding:24px 20px 30px;font-size:12.5px;color:#9ca3af;text-align:center">Nothing yet.</div>
</div>`;
		}

		var RAMP = ["#0d9488", "#14b8a6", "#2dd4bf", "#5eead4", "#99f6e4"];
		var total = slices.reduce(function (s, x) { return s + x.value; }, 0);
		var top = slices.slice(0, 5).map(function (s, i) {
			return { party: s.party, value: s.value, color: RAMP[i] };
		});
		var rest = slices.slice(5);
		if (rest.length) {
			top.push({
				party: rest.length + " more",
				value: rest.reduce(function (s, x) { return s + x.value; }, 0),
				color: "#e2e6ea",
			});
		}

		var R = 52, SW = 20, C = 2 * Math.PI * R, off = 0;
		var arcs = top.map(function (s, i) {
			var len = total ? s.value / total * C : 0;
			var pct = total ? Math.round(s.value / total * 100) : 0;
			/* dasharray leaves only the arc painted, and the default
			   pointer-events:visiblePainted means the hit area is that arc
			   and nothing else — so each slice hovers independently. */
			var a = '<circle class="dpd-arc" data-i="' + i +
				'" data-party="' + _esc(s.party) + '" data-value="' + s.value +
				'" data-pct="' + pct + '" cx="66" cy="66" r="' + R +
				'" fill="none" stroke="' + s.color +
				'" stroke-width="' + SW + '" stroke-dasharray="' + len + " " + (C - len) +
				'" stroke-dashoffset="' + (-off) + '"></circle>';
			off += len;
			return a;
		}).join("");

		var legend = top.map(function (s, i) {
			var pct = total ? Math.round(s.value / total * 100) : 0;
			return `<div class="dpd-leg" data-i="${i}" data-party="${_esc(s.party)}"
     data-value="${s.value}" data-pct="${pct}">
  <span class="dpd-dot" style="background:${s.color}"></span>
  <span class="dpd-leg-n">${_esc(s.party)}</span>
  <span class="dpd-mono dpd-leg-v">${_num(s.value)}</span>
  <span class="dpd-leg-p">${pct}%</span>
</div>`;
		}).join("");

		return `<div class="dpd-card" style="padding:0;overflow:hidden">
  ${this._cardHead(title, sub, this._cardTotal(slices))}
  <div class="dpd-donut-wrap">
    <div class="dpd-donut">
      <svg width="132" height="132" viewBox="0 0 132 132" style="transform:rotate(-90deg)">${arcs}</svg>
      <div class="dpd-donut-mid">
        <div class="dpd-lbl">Total</div>
        <div class="dpd-mono" style="font-size:15px;font-weight:700">&#8377;${_short(total)}</div>
      </div>
    </div>
    <div class="dpd-legend">${legend}</div>
  </div>
</div>`;
	}

	/* ---- purchase orders: ranked bars -------------------------------
	   Eleven suppliers with six of them under sixty thousand. A pie of
	   that is a ring of invisible slivers; ranked bars stay readable and
	   keep every name clickable. */
	_barsCard(slices, title, sub) {
		if (!slices.length) {
			return `<div class="dpd-card" style="padding:0;overflow:hidden">
  ${this._cardHead(title, sub)}
  <div style="padding:24px 20px 30px;font-size:12.5px;color:#9ca3af;text-align:center">Nothing yet.</div>
</div>`;
		}

		var max = slices[0].value || 1;
		var shown = slices.slice(0, 8);
		var bars = shown.map(function (s) {
			return `<div class="dpd-barrow" data-party="${_esc(s.party)}">
  <div class="dpd-barhead">
    <span class="dpd-bar-n">${_esc(s.party)}</span>
    <span class="dpd-mono dpd-bar-v">${_num(s.value)}</span>
  </div>
  <div class="dpd-prog"><i style="width:${Math.max(2, Math.round(s.value / max * 100))}%;background:#0d9488"></i></div>
</div>`;
		}).join("");

		var rest = slices.length - shown.length;
		return `<div class="dpd-card" style="padding:0;overflow:hidden">
  ${this._cardHead(title, sub, this._cardTotal(slices))}
  <div class="dpd-bars">${bars}${rest
		? '<div style="font-size:11.5px;color:#9ca3af;margin-top:2px">and ' + rest +
		  " more supplier" + (rest === 1 ? "" : "s") + "</div>" : ""}</div>
</div>`;
	}

	/* Hovering either the arc or its legend line lights the same slice and
	   shows the value — a donut without this is a pretty shape you cannot
	   read a number off. */
	_bindDonutHover(scope) {
		var $tip = $("#dpd-tip");
		if (!$tip.length) {
			$tip = $('<div class="dpd-tip" id="dpd-tip"></div>').appendTo(document.body);
		}

		function show(e, el) {
			var $e = $(el);
			var $donut = $e.closest(".dpd-donut-wrap").find(".dpd-donut");
			var i = $e.attr("data-i");
			$donut.addClass("hot").find("circle").removeClass("on")
				.filter('[data-i="' + i + '"]').addClass("on");
			$e.closest(".dpd-donut-wrap").find('.dpd-leg[data-i="' + i + '"]').addClass("on");

			$tip.html('<div class="t">' + _esc($e.attr("data-party")) + "</div>" +
				'<span class="v">&#8377;' + _num($e.attr("data-value")) + "</span>" +
				'<span class="p">' + $e.attr("data-pct") + "% of total</span>").addClass("show");
			move(e);
		}
		function move(e) {
			var w = $tip.outerWidth(), h = $tip.outerHeight();
			var x = e.clientX + 14, y = e.clientY - h - 10;
			if (x + w > window.innerWidth - 8) x = e.clientX - w - 14;
			if (y < 8) y = e.clientY + 18;
			$tip.css({ left: x + "px", top: y + "px" });
		}
		function hide() {
			$tip.removeClass("show");
			scope.find(".dpd-donut").removeClass("hot").find("circle").removeClass("on");
			scope.find(".dpd-leg").removeClass("on");
		}

		scope.on("mouseenter", ".dpd-arc, .dpd-leg", function (e) { show(e, this); });
		scope.on("mousemove", ".dpd-arc, .dpd-leg", move);
		scope.on("mouseleave", ".dpd-arc, .dpd-leg", hide);
	}

	/* A party row, a legend line and a bar all open the same place. */
	_bindParties(scope, period, fallbackCompany) {
		var self = this;

		function open(party, ptype, account, company) {
			company = company || fallbackCompany;
			if (!company) {
				frappe.show_alert({
					message: __("{0} works for more than one company — open the Party Ledger and pick one.", [party]),
					indicator: "orange",
				});
				return;
			}
			if (!account) {
				frappe.show_alert({
					message: __("No payable account found for {0}.", [party]),
					indicator: "orange",
				});
				return;
			}
			_openTab("/app/dux-party-ledger?" + $.param({
				company: company,
				party: party,
				party_type: ptype || "Supplier",
				account: account,
				party_label: party,
				from_date: period.from_date,
				to_date: period.to_date,
			}));
		}
		this._openParty = open;

		scope.find(".dpd-prow").on("click", function () {
			var $t = $(this);
			open($t.attr("data-party"), $t.attr("data-ptype"),
				$t.attr("data-account"), $t.attr("data-company"));
		});

		/* Charts carry only a name, so look the rest up in the same rows
		   the table was built from. "N more" is a bucket, not a party. */
		scope.find(".dpd-leg, .dpd-barrow").on("click", function () {
			var name = $(this).attr("data-party");
			var hit = (self._partyIndex || {})[name];
			if (hit) open(hit.party, hit.party_type, hit.account, hit.company);
		});
	}

	_cardHead(title, sub, right) {
		return `<div class="dpd-chead">
  <div><div class="dpd-h">${title}</div><div class="dpd-hs">${sub}</div></div>
  ${right || ""}
</div>`;
	}

	/* Both chart cards carry their total in the same place, so the work
	   order and purchase order totals can be compared at a glance without
	   reading either list. */
	_cardTotal(slices) {
		var total = slices.reduce(function (s, x) { return s + x.value; }, 0);
		return `<div class="dpd-ctot">
  <div class="dpd-lbl">Total</div>
  <div class="dpd-mono dpd-ctot-v">&#8377;${_num(total)}</div>
</div>`;
	}

	_bindDetail() {
		var self = this, d = this.detail;

		/* Charts pass a name only; the table rows carry the rest. */
		this._partyIndex = {};
		(d.parties.rows || []).forEach(function (r) { self._partyIndex[r.party] = r; });
		this._bindParties(this.$, d.period, d.project.company);
		this._bindDonutHover(this.$);

		this.$.find(".dpd-worow").on("click", function () {
			var wo = $(this).attr("data-wo");
			if (wo) _openTab("/app/work-order-contract/" + encodeURIComponent(wo));
		});
		this.$.find(".dpd-inv").on("click", function (e) {
			e.stopPropagation();
			_openTab("/app/purchase-invoice/" + encodeURIComponent($(this).attr("data-pi")));
		});

		this.$.find("#dpd-back").on("click", function (e) {
			e.preventDefault();
			self.backToPortfolio();
		});

		this.$.find("#dpd-open-erp").on("click", function () {
			_openTab("/app/project/" + encodeURIComponent(d.project.name));
		});

		/* A new tab, so the drill-down you were reading is still there when
		   you come back from the voucher. Same gesture the Trial Balance
		   page uses for its own drill-through. */
		this.$.find(".dpd-drow").on("click", function () {
			var dt = $(this).attr("data-doctype"), nm = $(this).attr("data-name");
			if (dt && nm) _openTab("/app/" + frappe.router.slug(dt) + "/" + encodeURIComponent(nm));
		});

		this.$.find("#dpd-gl, #dpd-all").on("click", function (e) {
			e.preventDefault();
			_openTab("/app/query-report/General%20Ledger?" + $.param({
				company: d.project.company,
				project: d.project.name,
				from_date: d.period.from_date,
				to_date: d.period.to_date,
				group_by: "Group by Voucher (Consolidated)",
			}));
		});
	}
}

})();
