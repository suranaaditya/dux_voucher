/* ============================================================
   Trial Balance  —  /app/dux-trial-balance
   Dux DigiTech · dux_voucher

   The Script Report (Dux Trial Balance) remains the engine: it is what
   gives Auto Email Report, Prepared Report and the formatted-TB export.
   This page is the surface people actually use. It calls the SAME
   execute(), so the two can never disagree — nothing is recomputed here.

   Design notes:
     * Numbers are the content. Everything else recedes: hairline rules,
       no vertical borders, tabular figures, one accent.
     * The tie state is the first thing you should see, so it is a banner
       and not a number you have to hunt for in a footer.
     * Provenance is shown, always. A reconciliation screen that will not
       say whether it read live GL or a nightly aggregate is not one you
       can defend in an audit.
   ============================================================ */

frappe.pages["dux-trial-balance"].on_page_load = function (wrapper) {
	try {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Trial Balance"),
			single_column: true,
		});
		window._dux_tb = new DuxTrialBalance(wrapper, page);
	} catch (e) {
		$(wrapper)
			.find(".layout-main-section")
			.html(`<div style="padding:40px;color:#dc2626">Error: ${e.message}</div>`);
		console.error("dux-trial-balance:", e);
	}
};

class DuxTrialBalance {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.companies = [];
		this.view = "By Account";
		this.collapsed = new Set();
		this.data = null;
		this.search = "";
		this.parties = {}; // account key -> party rows, fetched on demand
		this.partyOpen = new Set();

		this._styles();
		this._layout();
		this._bind();
		this._defaults();
		this._loadFiscalYears();
	}

	/* ---------------------------------------------------------- styles */
	_styles() {
		if (document.getElementById("dux-tb-styles")) return;
		const s = document.createElement("style");
		s.id = "dux-tb-styles";
		s.textContent = `
:root{
  --tb-bg:#ffffff; --tb-sunken:#f7f9fb; --tb-ink:#0f1f2b; --tb-ink-2:#51677a;
  --tb-ink-3:#8296a6; --tb-line:#e4eaef; --tb-line-2:#f1f5f8;
  --tb-accent:#0e7c86; --tb-accent-soft:#e6f4f5;
  --tb-dr:#b3261e; --tb-cr:#146b4a;
  --tb-warn:#a65a00; --tb-warn-soft:#fdf3e5;
  --tb-good-soft:#e8f5ee; --tb-bad-soft:#fdecea;
  --tb-shadow:0 1px 2px rgba(15,31,43,.05), 0 4px 16px rgba(15,31,43,.05);
}
[data-theme="dark"]{
  --tb-bg:#141c24; --tb-sunken:#0f161d; --tb-ink:#e8eef3; --tb-ink-2:#a9bccb;
  --tb-ink-3:#75899a; --tb-line:#243441; --tb-line-2:#1b2831;
  --tb-accent:#4fb3b8; --tb-accent-soft:#12313380;
  --tb-dr:#e98a80; --tb-cr:#6fc49c;
  --tb-warn:#d89a46; --tb-warn-soft:#2c2317;
  --tb-good-soft:#12291f; --tb-bad-soft:#2e1a18;
  --tb-shadow:0 1px 2px rgba(0,0,0,.3), 0 4px 16px rgba(0,0,0,.25);
}
.tb-wrap{padding:4px 0 12px;color:var(--tb-ink);
  font-feature-settings:"tnum" 1,"cv05" 1;}
.tb-card{background:var(--tb-bg);border:1px solid var(--tb-line);
  border-radius:12px;box-shadow:var(--tb-shadow);}

/* ---- filter bar ---- */
.tb-filters{padding:16px 18px;display:flex;flex-wrap:wrap;gap:14px;
  align-items:flex-end;margin-bottom:16px;}
.tb-f{display:flex;flex-direction:column;gap:6px;min-width:0;}
.tb-f > label{font-size:10.5px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;color:var(--tb-ink-3);}
.tb-input,.tb-select{height:36px;border:1px solid var(--tb-line);border-radius:8px;
  padding:0 11px;font-size:13.5px;color:var(--tb-ink);background:var(--tb-bg);
  outline:none;transition:border-color .15s,box-shadow .15s;font-family:inherit;}
.tb-input:focus,.tb-select:focus{border-color:var(--tb-accent);
  box-shadow:0 0 0 3px var(--tb-accent-soft);}
.tb-date{width:140px;}

/* segmented view switch — a dropdown hides that four views exist */
.tb-seg{display:inline-flex;background:var(--tb-sunken);border:1px solid var(--tb-line);
  border-radius:9px;padding:3px;gap:2px;}
.tb-seg button{border:0;background:transparent;color:var(--tb-ink-2);
  font-size:12.5px;font-weight:600;padding:6px 12px;border-radius:6px;
  cursor:pointer;white-space:nowrap;font-family:inherit;transition:all .12s;}
.tb-seg button:hover{color:var(--tb-ink);}
.tb-seg button.on{background:var(--tb-bg);color:var(--tb-accent);
  box-shadow:0 1px 2px rgba(15,31,43,.08);}

/* company picker */
.tb-co{position:relative;min-width:280px;}
.tb-chips{display:flex;flex-wrap:wrap;gap:5px;align-items:center;
  min-height:36px;border:1px solid var(--tb-line);border-radius:8px;
  padding:4px 8px;background:var(--tb-bg);cursor:text;}
.tb-chip{display:inline-flex;align-items:center;gap:6px;background:var(--tb-accent-soft);
  color:var(--tb-accent);border-radius:6px;padding:3px 8px;font-size:12px;
  font-weight:600;max-width:230px;}
.tb-chip .x{cursor:pointer;opacity:.6;font-size:14px;line-height:1;}
.tb-chip .x:hover{opacity:1;}
.tb-chip .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tb-chip.grp{background:var(--tb-warn-soft);color:var(--tb-warn);}
.tb-chips input{border:0;outline:0;background:transparent;flex:1;min-width:110px;
  height:26px;font-size:13px;color:var(--tb-ink);font-family:inherit;}
.tb-drop{position:absolute;top:calc(100% + 4px);left:0;right:0;z-index:50;
  background:var(--tb-bg);border:1px solid var(--tb-line);border-radius:10px;
  box-shadow:var(--tb-shadow);max-height:300px;overflow-y:auto;display:none;}
.tb-drop.open{display:block;}
.tb-opt{padding:9px 12px;cursor:pointer;font-size:13px;display:flex;
  justify-content:space-between;gap:10px;align-items:center;}
.tb-opt:hover{background:var(--tb-sunken);}
.tb-opt .badge{font-size:10px;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;color:var(--tb-warn);background:var(--tb-warn-soft);
  padding:2px 6px;border-radius:4px;white-space:nowrap;}

/* toggles */
.tb-toggles{display:flex;flex-wrap:wrap;gap:14px;align-items:center;
  padding:0 18px 16px;}
.tb-tg{display:inline-flex;align-items:center;gap:7px;font-size:12.5px;
  color:var(--tb-ink-2);cursor:pointer;user-select:none;}
.tb-tg input{width:15px;height:15px;accent-color:var(--tb-accent);cursor:pointer;}
.tb-btn{height:36px;padding:0 16px;border-radius:8px;font-size:13px;font-weight:600;
  cursor:pointer;border:1px solid var(--tb-line);background:var(--tb-bg);
  color:var(--tb-ink);font-family:inherit;transition:all .15s;}
.tb-btn:hover{background:var(--tb-sunken);}
.tb-btn-primary{background:var(--tb-accent);border-color:var(--tb-accent);color:#fff;}
.tb-btn-primary:hover{filter:brightness(1.08);background:var(--tb-accent);}

/* ---- provenance ---- */
.tb-prov{display:flex;flex-wrap:wrap;gap:8px;align-items:center;
  margin-bottom:14px;font-size:12px;color:var(--tb-ink-2);}
.tb-pill{display:inline-flex;align-items:center;gap:6px;background:var(--tb-sunken);
  border:1px solid var(--tb-line);border-radius:999px;padding:3px 11px;
  font-size:11.5px;font-weight:600;}
.tb-pill.warn{background:var(--tb-warn-soft);border-color:transparent;color:var(--tb-warn);}
.tb-pill.dot::before{content:"";width:6px;height:6px;border-radius:50%;
  background:var(--tb-accent);}

/* ---- table ---- */
table.tb{width:100%;border-collapse:separate;border-spacing:0;font-size:13px;}
table.tb thead th{position:sticky;top:0;z-index:2;background:var(--tb-bg);
  text-align:right;font-size:10.5px;font-weight:700;letter-spacing:.07em;
  text-transform:uppercase;color:var(--tb-ink-3);padding:12px 14px;
  border-bottom:1px solid var(--tb-line);white-space:nowrap;}
table.tb thead th:first-child{text-align:left;}
table.tb td{padding:9px 14px;border-bottom:1px solid var(--tb-line-2);
  text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;}
table.tb td:first-child{text-align:left;white-space:normal;}
table.tb tbody tr:hover td{background:var(--tb-sunken);}
.tb-name{display:flex;align-items:center;gap:7px;}
.tb-caret{width:16px;height:16px;flex:none;display:inline-flex;align-items:center;
  justify-content:center;cursor:pointer;color:var(--tb-ink-3);
  transition:transform .15s;font-size:10px;}
.tb-caret.collapsed{transform:rotate(-90deg);}
.tb-caret.leaf{visibility:hidden;}
.tb-lbl{cursor:pointer;}
.tb-lbl:hover{color:var(--tb-accent);text-decoration:underline;}
tr.grp > td{font-weight:650;}
tr.lvl0 > td:first-child{font-weight:700;}
tr.total > td{border-top:2px solid var(--tb-line);border-bottom:0;
  font-weight:700;background:var(--tb-sunken);position:sticky;bottom:0;}
tr.computed td{color:var(--tb-warn);font-style:italic;}
.tb-dr{color:var(--tb-dr);} .tb-cr{color:var(--tb-cr);}
.tb-nil{color:var(--tb-ink-3);opacity:.5;}
.tb-flag{display:inline-block;font-size:9.5px;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;padding:1.5px 5px;border-radius:4px;margin-left:6px;
  background:var(--tb-warn-soft);color:var(--tb-warn);white-space:nowrap;}
.tb-unatt{color:var(--tb-ink-3);font-style:italic;}

/* Context bar — replaces four KPI cards. Closing Dr/Cr were already the
   Total row and row-count was trivia; only the tie status earned space. */
.tb-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;
  padding:9px 14px;border:1px solid var(--tb-line);border-radius:10px;
  background:var(--tb-bg);margin-bottom:10px;}
.tb-bar .ctx{font-size:12.5px;color:var(--tb-ink-2);font-weight:550;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:46vw;}
.tb-bar .sp{flex:1 1 auto;}
.tb-tie{display:inline-flex;align-items:center;gap:6px;font-size:12.5px;
  font-weight:650;padding:3px 10px;border-radius:20px;white-space:nowrap;}
.tb-tie.ok{background:var(--tb-good-soft);color:var(--tb-cr);}
.tb-tie.off{background:var(--tb-bad-soft);color:var(--tb-dr);}
.tb-mini{height:30px;border:1px solid var(--tb-line);border-radius:8px;
  background:var(--tb-bg);color:var(--tb-ink-2);font-size:12.5px;font-weight:600;
  padding:0 11px;cursor:pointer;white-space:nowrap;}
.tb-mini:hover{background:var(--tb-sunken);}
.tb-popwrap{position:relative;}
.tb-pop{position:absolute;right:0;top:36px;z-index:40;min-width:250px;
  background:var(--tb-bg);border:1px solid var(--tb-line);border-radius:10px;
  box-shadow:0 12px 32px rgba(16,33,46,.14);padding:12px 14px;display:none;}
.tb-pop.open{display:block;}
.tb-pop label{display:flex;align-items:center;gap:9px;font-size:13px;
  color:var(--tb-ink-2);padding:6px 0;cursor:pointer;}

/* The table is the report — let it own the viewport, and keep the header
   and the Total row pinned so context never scrolls away. */
.tb-tablewrap{overflow:auto;max-height:calc(100vh - 148px);}
.tb thead th{position:sticky;top:0;z-index:3;background:var(--tb-sunken);}
.tb tfoot td{position:sticky;bottom:0;z-index:3;background:var(--tb-bg);
  border-top:2px solid var(--tb-line-2);font-weight:700;}
.tb tfoot td:first-child{font-weight:700;}
.tb-ctrl{font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:1.5px 6px;border-radius:4px;margin-left:7px;background:var(--tb-accent-soft);
  color:var(--tb-accent);white-space:nowrap;}
tr.party > td{background:var(--tb-sunken);}
tr.party:hover > td{background:var(--tb-line-2);}
.tb-ptype{font-size:10px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:var(--tb-ink-3);margin-left:8px;}
.tb-empty{padding:64px 20px;text-align:center;color:var(--tb-ink-3);font-size:14px;}
.tb-empty strong{display:block;color:var(--tb-ink-2);font-size:15px;margin-bottom:6px;}
@media(max-width:900px){
  .tb-tablewrap{max-height:none;}
  table.tb{font-size:12px;}
  table.tb td,table.tb thead th{padding:8px 9px;}
  .tb-co{min-width:220px;}
}
`;
		document.head.appendChild(s);
	}

	/* ---------------------------------------------------------- layout */
	_layout() {
		const views = ["By Account", "By Party", "Account -> Party", "By Company"];
		const seg = views
			.map(
				(v) =>
					`<button data-view="${frappe.utils.escape_html(v)}" class="${
						v === this.view ? "on" : ""
					}">${frappe.utils.escape_html(v.replace("->", "→"))}</button>`
			)
			.join("");

		$(this.wrapper).find(".layout-main-section").html(`
<div class="tb-wrap">

  <div class="tb-card tb-filters">
    <div class="tb-f tb-co">
      <label>${__("Company or Trust")}</label>
      <div class="tb-chips" id="tb-chips">
        <input id="tb-co-inp" placeholder="${__("Search…")}" autocomplete="off">
      </div>
      <div class="tb-drop" id="tb-drop"></div>
    </div>

    <div class="tb-f">
      <label>${__("View")}</label>
      <div class="tb-seg" id="tb-seg">${seg}</div>
    </div>

    <div class="tb-f">
      <label>${__("Fiscal Year")}</label>
      <select class="tb-select" id="tb-fy" style="min-width:150px"></select>
    </div>

    <div class="tb-f">
      <label>${__("From")}</label>
      <input type="date" class="tb-input tb-date" id="tb-from">
    </div>

    <div class="tb-f">
      <label>${__("To")}</label>
      <input type="date" class="tb-input tb-date" id="tb-to">
    </div>

    <div class="tb-f">
      <label>&nbsp;</label>
      <button class="tb-btn tb-btn-primary" id="tb-run">${__("Run")}</button>
    </div>
  </div>

  <div class="tb-bar" id="tb-bar" style="display:none">
    <span class="ctx" id="tb-ctx"></span>
    <span id="tb-pills"></span>
    <span class="sp"></span>
    <span id="tb-tie"></span>
    <input class="tb-input" id="tb-search" placeholder="${__("Filter rows…")}"
           style="height:30px;width:160px">
    <span class="tb-popwrap">
      <button class="tb-mini" id="tb-opts">${__("Options")}</button>
      <div class="tb-pop" id="tb-pop">
        <label><input type="checkbox" id="tb-net" checked> ${__("Net opening / closing")}</label>
        <label><input type="checkbox" id="tb-grp" checked> ${__("Group accounts")}</label>
        <label><input type="checkbox" id="tb-zero"> ${__("Zero rows")}</label>
        <label><input type="checkbox" id="tb-pl"> ${__("Carry prior-year P&L")}</label>
        <label><input type="checkbox" id="tb-live"> ${__("Force live query")}</label>
      </div>
    </span>
    <button class="tb-mini" id="tb-edit">${__("Filters")}</button>
  </div>

  <div class="tb-card" id="tb-result">
    <div class="tb-empty">
      <strong>${__("Nothing run yet")}</strong>
      ${__("Pick a company or a trust, then Run.")}
    </div>
  </div>
</div>`);
	}

	/* ----------------------------------------------------------- events */
	_bind() {
		const $w = $(this.wrapper);

		$w.on("click", "#tb-seg button", (e) => {
			this.view = $(e.currentTarget).data("view");
			$w.find("#tb-seg button").removeClass("on");
			$(e.currentTarget).addClass("on");
			if (this.data) this.run();
		});

		$w.on("click", "#tb-run", () => this.run());

		// Options popover — these are set-once choices, so they live behind a
		// button rather than occupying a permanent row above the numbers.
		$w.on("click", "#tb-opts", (e) => {
			e.stopPropagation();
			$w.find("#tb-pop").toggleClass("open");
		});
		$w.on("click", "#tb-pop", (e) => e.stopPropagation());
		// Changing an option re-runs: each one changes what the server
		// computes, so leaving stale numbers on screen would be a lie.
		$w.on("change", "#tb-pop input[type=checkbox]", () => this.run());

		// Bring the filter panel back.
		$w.on("click", "#tb-edit", () => {
			$w.find(".tb-filters").toggle();
			$w.find("#tb-pop").removeClass("open");
		});
		$w.on("click", "#tb-chips", () => $w.find("#tb-co-inp").focus());

		let t = null;
		$w.on("input", "#tb-co-inp", (e) => {
			clearTimeout(t);
			const txt = e.target.value;
			t = setTimeout(() => this._searchCompanies(txt), 180);
		});
		$w.on("focus", "#tb-co-inp", () => this._searchCompanies($w.find("#tb-co-inp").val()));
		$(document).on("click.duxtb", (e) => {
			if (!$(e.target).closest("#tb-opts,#tb-pop").length)
				$w.find("#tb-pop").removeClass("open");
			if (!$(e.target).closest(".tb-co").length) $w.find("#tb-drop").removeClass("open");
		});

		$w.on("click", ".tb-opt", (e) => {
			const v = $(e.currentTarget).data("v");
			const grp = $(e.currentTarget).data("grp");
			if (!this.companies.find((c) => c.value === v)) {
				this.companies.push({ value: v, is_group: grp });
				this._renderChips();
			}
			$w.find("#tb-co-inp").val("");
			$w.find("#tb-drop").removeClass("open");
		});

		$w.on("click", ".tb-chip .x", (e) => {
			e.stopPropagation();
			const v = $(e.currentTarget).closest(".tb-chip").data("v");
			this.companies = this.companies.filter((c) => c.value !== v);
			this._renderChips();
		});

		$w.on("change", "#tb-fy", (e) => {
			const fy = this.fiscalYears.find((f) => f.name === e.target.value);
			if (fy) {
				$w.find("#tb-from").val(fy.year_start_date);
				$w.find("#tb-to").val(fy.year_end_date);
			}
		});

		$w.on("click", ".tb-caret:not(.leaf)", (e) => {
			const $tr = $(e.currentTarget).closest("tr");
			const key = $tr.data("key");
			const idx = $tr.data("idx");
			const row = (this.data && this.data.rows) || [];
			const r = row[idx];

			// A control account has no children in the chart of accounts,
			// so its caret opens the PARTIES behind it instead — in place,
			// rather than sending the user off to another view.
			if (r && r.is_control) {
				if (this.partyOpen.has(key)) {
					this.partyOpen.delete(key);
					this._renderTable();
				} else {
					this._loadParties(key, r);
				}
				return;
			}

			if (this.collapsed.has(key)) this.collapsed.delete(key);
			else this.collapsed.add(key);
			this._renderTable();
		});

		$w.on("click", ".tb-lbl", (e) => this._drill($(e.currentTarget).closest("tr").data("idx")));

		let st = null;
		$w.on("input", "#tb-search", (e) => {
			clearTimeout(st);
			const v = e.target.value;
			st = setTimeout(() => {
				this.search = (v || "").toLowerCase();
				this._renderTable();
			}, 150);
		});

		this.page.set_secondary_action(__("Excel"), () => this._excel());
		this.page.add_menu_item(__("Print"), () => window.print());
		this.page.add_menu_item(__("Rebuild aggregate"), () => this._rebuild());
		this.page.add_menu_item(__("Open as classic report"), () =>
			frappe.set_route("query-report", "Dux Trial Balance")
		);
	}

	_defaults() {
		// Month-ALIGNED by default, deliberately.
		//
		// A "last 12 months from today" default lands mid-month, and the
		// monthly aggregate can only answer whole months — so every default
		// run would silently take the 38-second live path. Aligning the
		// default means the common case is fast, and an accountant reading
		// a trial balance wants month boundaries anyway.
		const today = frappe.datetime.get_today();
		const firstOfThis = today.slice(0, 8) + "01";
		const from = frappe.datetime.add_months(firstOfThis, -11);
		const to = frappe.datetime.add_days(frappe.datetime.add_months(firstOfThis, 1), -1);
		$(this.wrapper).find("#tb-from").val(from);
		$(this.wrapper).find("#tb-to").val(to);
	}

	_loadFiscalYears() {
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.get_fiscal_years",
			callback: (r) => {
				this.fiscalYears = r.message || [];
				const opts = [`<option value="">${__("Custom range")}</option>`].concat(
					this.fiscalYears.map(
						(f) =>
							`<option value="${frappe.utils.escape_html(f.name)}">${frappe.utils.escape_html(
								f.name
							)} &nbsp; ${f.year_start_date} → ${f.year_end_date}</option>`
					)
				);
				const $fy = $(this.wrapper).find("#tb-fy");
				$fy.html(opts.join(""));

				// Preselect the fiscal year containing today. This site has
				// OVERLAPPING fiscal years, so pick the latest-starting one
				// that covers today rather than pretending there is only one.
				const today = frappe.datetime.get_today();
				const covering = this.fiscalYears
					.filter((f) => f.year_start_date <= today && f.year_end_date >= today)
					.sort((a, b) => (a.year_start_date < b.year_start_date ? 1 : -1))[0];
				if (covering) {
					$fy.val(covering.name);
					$(this.wrapper).find("#tb-from").val(covering.year_start_date);
					$(this.wrapper).find("#tb-to").val(covering.year_end_date);
				}
			},
		});
	}

	_searchCompanies(txt) {
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.search_companies",
			args: { txt: txt || "" },
			callback: (r) => {
				const rows = r.message || [];
				const $d = $(this.wrapper).find("#tb-drop");
				if (!rows.length) {
					$d.html(`<div class="tb-opt" style="color:var(--tb-ink-3)">${__("No match")}</div>`);
				} else {
					$d.html(
						rows
							.map(
								(o) =>
									`<div class="tb-opt" data-v="${frappe.utils.escape_html(o.value)}" data-grp="${
										o.is_group ? 1 : 0
									}">
                    <span>${frappe.utils.escape_html(o.value)}</span>
                    ${
											o.is_group
												? `<span class="badge">${__("trust")} · ${o.member_count}</span>`
												: `<span style="color:var(--tb-ink-3);font-size:11px">${frappe.utils.escape_html(
														o.abbr || ""
												  )}</span>`
										}
                  </div>`
							)
							.join("")
					);
				}
				$d.addClass("open");
			},
		});
	}

	_renderChips() {
		const $c = $(this.wrapper).find("#tb-chips");
		$c.find(".tb-chip").remove();
		const html = this.companies
			.map(
				(c) =>
					`<span class="tb-chip ${c.is_group ? "grp" : ""}" data-v="${frappe.utils.escape_html(
						c.value
					)}"><span class="n">${frappe.utils.escape_html(c.value)}</span><span class="x">×</span></span>`
			)
			.join("");
		$c.prepend(html);
	}

	/* -------------------------------------------------------------- run */
	run() {
		const $w = $(this.wrapper);
		if (!this.companies.length) {
			frappe.show_alert({ message: __("Pick a company or a trust first."), indicator: "orange" });
			return;
		}
		const filters = {
			company: this.companies.map((c) => c.value),
			view: this.view,
			from_date: $w.find("#tb-from").val(),
			to_date: $w.find("#tb-to").val(),
			show_net_values: $w.find("#tb-net").is(":checked") ? 1 : 0,
			show_group_accounts: $w.find("#tb-grp").is(":checked") ? 1 : 0,
			show_zero_values: $w.find("#tb-zero").is(":checked") ? 1 : 0,
			show_unclosed_fy_pl_balances: $w.find("#tb-pl").is(":checked") ? 1 : 0,
			force_live: $w.find("#tb-live").is(":checked") ? 1 : 0,
		};
		this.filters = filters;

		$w.find("#tb-result").html(`<div class="tb-empty">${__("Running…")}</div>`);
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.get_trial_balance",
			args: { filters: JSON.stringify(filters) },
			callback: (r) => {
				this.data = r.message;
				this.collapsed = new Set();
				this.parties = {};
				this.partyOpen = new Set();
				// Filters are a set-up step, not a thing you stare at. Fold
				// them away once there is a report to look at.
				$w.find(".tb-filters").hide();
				$w.find("#tb-bar").css("display", "flex");
				this._renderStatusBar();
				this._renderTable();
			},
			error: () => {
				$w.find("#tb-result").html(
					`<div class="tb-empty"><strong>${__("Could not run")}</strong>${__(
						"Check the filters and try again."
					)}</div>`
				);
			},
		});
	}

	_fmt(v) {
		if (!v || Math.abs(v) < 0.005) return null;
		return new Intl.NumberFormat("en-IN", {
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		}).format(v);
	}

	_cell(v, cls) {
		const f = this._fmt(v);
		if (f === null) return `<td class="tb-nil">—</td>`;
		return `<td class="${cls || ""}">${f}</td>`;
	}

	_renderStatusBar() {
		const d = this.data || {};
		const rows = d.rows || [];
		const $w = $(this.wrapper);
		const total = rows.find((r) => r.is_total);

		const co = this.companies.map((c) => c.value);
		const coTxt =
			co.length === 1
				? co[0]
				: `${co.length} ${__("selected")} · ${(d.companies || []).length} ${__("companies")}`;
		const fmtD = (v) => (v ? frappe.datetime.str_to_user(v) : "");
		$w.find("#tb-ctx").text(
			`${coTxt}  ·  ${this.view}  ·  ${fmtD(this.filters.from_date)} → ${fmtD(
				this.filters.to_date
			)}`
		);

		const pills = [];
		pills.push(
			`<span class="tb-pill dot">${
				d.source === "aggregate" ? __("Monthly aggregate") : __("Live GL")
			}${d.source_built_at ? " · " + String(d.source_built_at).slice(0, 16) : ""}</span>`
		);
		const mism = rows.filter((r) => r.mismatch).length;
		if (mism) pills.push(`<span class="tb-pill warn">${mism} ${__("mismatch")}</span>`);
		const unatt = rows.filter((r) => r.is_unattributed).length;
		if (unatt) pills.push(`<span class="tb-pill warn">${unatt} ${__("unattributed")}</span>`);
		if (rows.find((r) => r.is_computed))
			pills.push(`<span class="tb-pill warn">${__("computed carry-forward")}</span>`);
		$w.find("#tb-pills").html(pills.join(""));

		if (total) {
			const diff = (total.closing_debit || 0) - (total.closing_credit || 0);
			const tied = Math.abs(diff) < 0.005;
			$w.find("#tb-tie").html(
				`<span class="tb-tie ${tied ? "ok" : "off"}">${
					tied ? "✓ " + __("Balanced") : "⚠ " + __("Out by") + " " + this._fmt(diff)
				}</span>`
			);
		} else {
			$w.find("#tb-tie").empty();
		}
	}

	_visible(rows) {
		// Hide descendants of a collapsed node, and apply the row filter.
		const hidden = new Set();
		const out = [];
		for (const r of rows) {
			// The Total is rendered in a sticky <tfoot>, so it must NOT also
			// appear in the body. While the table was short enough to fit the
			// viewport the pinned footer sat directly under the body's copy
			// and the two read as one row; expanding a control account grew
			// the table past the fold and the duplicate became visible.
			if (r.is_total) continue;
			const pa = r.parent_account;
			if (pa && (hidden.has(pa) || this.collapsed.has(pa))) {
				hidden.add(r.account);
				continue;
			}
			if (this.search) {
				const hay = `${r.account_name || ""} ${r.party || ""} ${r.party_name || ""} ${
					r.company || ""
				}`.toLowerCase();
				if (!hay.includes(this.search)) continue;
			}
			out.push(r);
		}
		return out;
	}

	_loadParties(key, row) {
		if (this.parties[key]) {
			this.partyOpen.add(key);
			this._renderTable();
			return;
		}
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.get_account_parties",
			args: {
				filters: JSON.stringify(this.filters || {}),
				accounts: JSON.stringify(row.members || [row.account]),
			},
			callback: (r) => {
				this.parties[key] = r.message || [];
				this.partyOpen.add(key);
				this._renderTable();
				if (!this.parties[key].length) {
					frappe.show_alert({
						message: __("No parties on this account for the period."),
						indicator: "blue",
					});
				}
			},
		});
	}

	_partyRowHtml(p, indent) {
		let name = frappe.utils.escape_html(p.label || "");
		if (p.is_unattributed) name = `<span class="tb-unatt">${name}</span>`;
		if (p.mismatch) name += `<span class="tb-flag">${__("wrong party type")}</span>`;
		const type = p.party_type
			? `<span class="tb-ptype">${frappe.utils.escape_html(p.party_type)}</span>`
			: "";
		return `<tr class="party" data-party="1" data-acct="${frappe.utils.escape_html(
			p._acct || ""
		)}" data-pt="${frappe.utils.escape_html(
			p.party_type || ""
		)}" data-p="${frappe.utils.escape_html(p.party || "")}">
      <td><div class="tb-name" style="padding-left:${indent + 18}px">
        <span class="tb-caret leaf">▼</span>
        <span class="tb-lbl">${name}</span>${type}
      </div></td>
      ${this._cell(p.opening_debit)}${this._cell(p.opening_credit)}
      ${this._cell(p.debit)}${this._cell(p.credit)}
      ${this._cell(p.closing_debit, "tb-dr")}${this._cell(p.closing_credit, "tb-cr")}</tr>`;
	}

	_renderTable() {
		const d = this.data || {};
		const rows = d.rows || [];
		const $r = $(this.wrapper).find("#tb-result");
		// Expanding a row re-renders the whole table, which destroys the
		// scroller and sends you back to the top. Carry the offset across.
		const keepTop = $r.find(".tb-tablewrap").scrollTop() || 0;
		if (!rows.length) {
			$r.html(
				`<div class="tb-empty"><strong>${__("No rows")}</strong>${__(
					"Nothing matched this period."
				)}</div>`
			);
			return;
		}

		const isParty = this.view === "By Party";
		const isCo = this.view === "By Company";
		const first = isParty ? __("Party") : isCo ? __("Company") : __("Account");

		const kids = new Set(rows.map((r) => r.parent_account).filter(Boolean));
		const vis = this._visible(rows);

		const body = vis
			.map((r, i) => {
				const idx = rows.indexOf(r);
				if (r.is_total) {
					return `<tr class="total"><td>${frappe.utils.escape_html(
						String(r.account_name || r.label || __("Total")).replace(/^'|'$/g, "")
					)}</td>
          ${this._cell(r.opening_debit)}${this._cell(r.opening_credit)}
          ${this._cell(r.debit)}${this._cell(r.credit)}
          ${this._cell(r.closing_debit, "tb-dr")}${this._cell(r.closing_credit, "tb-cr")}</tr>`;
				}

				// A control account gets a caret even though the chart of
				// accounts gives it no children — it opens into its parties.
				const hasKids = kids.has(r.account) || r.is_control;
				const collapsed = r.is_control
					? !this.partyOpen.has(r.account)
					: this.collapsed.has(r.account);
				const indent = (r.indent || 0) * 18;
				let name = frappe.utils.escape_html(
					r.account_name || r.party_name || r.company || r.party || ""
				);
				if (r.is_unattributed) name = `<span class="tb-unatt">${name}</span>`;
				if (r.mismatch) name += `<span class="tb-flag">${__("wrong party type")}</span>`;

				const cls = [
					r.is_group_account ? "grp" : "",
					(r.indent || 0) === 0 ? "lvl0" : "",
					r.is_computed ? "computed" : "",
				]
					.filter(Boolean)
					.join(" ");

				let html = `<tr class="${cls}" data-key="${frappe.utils.escape_html(
					r.account || ""
				)}" data-idx="${idx}">
        <td><div class="tb-name" style="padding-left:${indent}px">
          <span class="tb-caret ${hasKids ? "" : "leaf"} ${
					collapsed ? "collapsed" : ""
				}">▼</span>
          <span class="tb-lbl">${name}</span>
          ${
						r.is_control
							? `<span class="tb-ctrl" title="${__(
									"Opens into the parties behind this account"
							  )}">${__("parties")}</span>`
							: ""
					}
        </div></td>
        ${this._cell(r.opening_debit)}${this._cell(r.opening_credit)}
        ${this._cell(r.debit)}${this._cell(r.credit)}
        ${this._cell(r.closing_debit, "tb-dr")}${this._cell(r.closing_credit, "tb-cr")}</tr>`;

				if (r.is_control && this.partyOpen.has(r.account)) {
					const kidsRows = this.parties[r.account] || [];
					html += kidsRows.map((p) => this._partyRowHtml(p, indent)).join("");
					if (!kidsRows.length) {
						html += `<tr class="party"><td colspan="7" style="padding-left:${
							indent + 36
						}px;color:var(--tb-ink-3);font-style:italic">${__(
							"No parties on this account for the period."
						)}</td></tr>`;
					}
				}
				return html;
			})
			.join("");

		const tot = rows.find((r) => r.is_total);
		const foot = tot
			? `<tfoot><tr>
          <td>${__("Total")}</td>
          ${this._cell(tot.opening_debit)}${this._cell(tot.opening_credit)}
          ${this._cell(tot.debit)}${this._cell(tot.credit)}
          ${this._cell(tot.closing_debit, "tb-dr")}${this._cell(tot.closing_credit, "tb-cr")}
        </tr></tfoot>`
			: "";

		$r.html(`<div class="tb-tablewrap"><table class="tb">
      <thead><tr>
        <th>${first}</th>
        <th>${__("Opening (Dr)")}</th><th>${__("Opening (Cr)")}</th>
        <th>${__("Debit")}</th><th>${__("Credit")}</th>
        <th>${__("Closing (Dr)")}</th><th>${__("Closing (Cr)")}</th>
      </tr></thead><tbody>${body}</tbody>${foot}</table></div>`);

		if (keepTop) $r.find(".tb-tablewrap").scrollTop(keepTop);
	}

	_drill(idx) {
		const r = (this.data.rows || [])[idx];
		if (!r || r.is_total || r.is_computed) return;
		const f = this.filters || {};
		frappe.route_options = {
			company: r.company || (this.data.companies || [])[0],
			from_date: f.from_date,
			to_date: f.to_date,
		};
		if (r.party) {
			frappe.route_options.party = r.party;
			frappe.route_options.party_type = r.party_type;
			frappe.route_options.account = r.parent_account || r.account;
			frappe.set_route("dux-party-ledger");
		} else if (!r.is_group_account) {
			frappe.route_options.account = r.account;
			frappe.set_route("dux-ledger");
		}
	}

	_excel() {
		if (!this.data) {
			frappe.show_alert({ message: __("Run the report first."), indicator: "orange" });
			return;
		}
		frappe.set_route("query-report", "Dux Trial Balance");
		frappe.show_alert({
			message: __("Opening the classic report — use Menu → Export there."),
			indicator: "blue",
		});
	}

	_rebuild() {
		frappe.confirm(
			__("Rebuild the monthly aggregate now? This reads the ledger for every company under a trust."),
			() => {
				frappe.call({
					method: "dux_voucher.dux_voucher.api.tb_aggregate.rebuild",
					freeze: true,
					freeze_message: __("Rebuilding…"),
					callback: (r) => {
						if (r.message) {
							frappe.show_alert({
								message: __("Rebuilt {0} rows across {1} companies in {2}s", [
									r.message.rows,
									r.message.companies,
									r.message.seconds,
								]),
								indicator: "green",
							});
							if (this.data) this.run();
						}
					},
				});
			}
		);
	}
}
