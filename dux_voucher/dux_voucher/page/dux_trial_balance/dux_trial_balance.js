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
		// Tally shows Opening and Closing as one signed column each. The
		// split Dr/Cr form is available for anyone who wants the strict
		// six-column presentation.
		this.splitCols = false;

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
/* Do not let the company field grow with its contents — a long name
   used to push From/To/Run onto a second line and the whole bar went
   lopsided. The chip truncates instead; the layout stays put. */
.tb-co{position:relative;flex:0 1 300px;min-width:240px;}
.tb-dates{display:flex;gap:14px;align-items:flex-end;}
.tb-chips{display:flex;flex-wrap:wrap;gap:5px;align-items:center;
  min-height:36px;border:1px solid var(--tb-line);border-radius:8px;
  padding:4px 8px;background:var(--tb-bg);cursor:text;}
.tb-chip{display:inline-flex;align-items:center;gap:6px;background:var(--tb-accent-soft);
  color:var(--tb-accent);border-radius:6px;padding:3px 8px;font-size:12px;
  font-weight:600;max-width:150px;}
.tb-chip .x{cursor:pointer;opacity:.6;font-size:14px;line-height:1;}
.tb-chip .x:hover{opacity:1;}
.tb-chip .n{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tb-chip.grp{background:var(--tb-warn-soft);color:var(--tb-warn);}
.tb-chips input{border:0;outline:0;background:transparent;flex:1;min-width:60px;
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
/* Fixed layout so the account column keeps a real share of the width.
   With auto layout the six nowrap numeric columns claim whatever they
   want and the names collapse to "Accou…". */
table.tb{width:100%;border-collapse:separate;border-spacing:0;font-size:12.5px;
  line-height:1.35;table-layout:fixed;}
table.tb th:first-child,table.tb td:first-child{width:34%;}
table.tb th:not(:first-child),table.tb td:not(:first-child){width:11%;}
/* Four columns leave far more room for names — which is most of what a
   trial balance is read down. */
table.tb.cols4 th:first-child,table.tb.cols4 td:first-child{width:46%;}
table.tb.cols4 th:not(:first-child),table.tb.cols4 td:not(:first-child){width:13.5%;}
.tb-sfx{font-size:9px;font-weight:700;margin-left:4px;opacity:.75;
  letter-spacing:.03em;}
.tb-searching{padding:6px 14px;font-size:12px;color:var(--tb-ink-3);
  background:var(--tb-sunken);border-bottom:1px solid var(--tb-line);}
table.tb thead th{position:sticky;top:0;z-index:2;background:var(--tb-bg);
  text-align:right;font-size:10.5px;font-weight:700;letter-spacing:.07em;
  text-transform:uppercase;color:var(--tb-ink-3);padding:7px 12px;
  border-bottom:1px solid var(--tb-line);white-space:nowrap;}
table.tb thead th:first-child{text-align:left;}
table.tb td{padding:4px 12px;border-bottom:1px solid var(--tb-line-2);
  text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums;}
/* Account names stay on one line — a wrapped name would make rows
   ragged, and ragged rows are far harder to scan down a column of
   figures than a truncated name is to read. */
table.tb td:first-child{text-align:left;white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis;}
table.tb tbody tr:hover td{background:var(--tb-sunken);}
.tb-name{display:flex;align-items:center;gap:6px;min-width:0;}
.tb-name > .tb-lbl{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.tb-caret{width:14px;height:14px;flex:none;display:inline-flex;align-items:center;
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
.tb-flag{display:inline-block;font-size:9px;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;padding:0 5px;border-radius:4px;margin-left:6px;
  line-height:15px;background:var(--tb-warn-soft);color:var(--tb-warn);
  white-space:nowrap;flex:none;}
.tb-unatt{color:var(--tb-ink-3);font-style:italic;}

/* Context bar — replaces four KPI cards. Closing Dr/Cr were already the
   Total row and row-count was trivia; only the tie status earned space. */
.tb-bar{display:flex;align-items:center;gap:12px;flex-wrap:nowrap;
  padding:9px 14px;border:1px solid var(--tb-line);border-radius:10px;
  background:var(--tb-bg);margin-bottom:10px;}
/* The context text yields before the controls do — it truncates with the
   full list on hover, rather than shoving Filters onto a second line. */
.tb-bar .ctx{font-size:12.5px;color:var(--tb-ink-2);font-weight:550;
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  flex:0 1 auto;min-width:60px;max-width:32vw;cursor:help;}
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
.tb-tablewrap{overflow:auto;max-height:calc(100vh - 140px);}
.tb thead th{position:sticky;top:0;z-index:3;background:var(--tb-sunken);}
.tb tfoot td{position:sticky;bottom:0;z-index:3;background:var(--tb-bg);
  border-top:2px solid var(--tb-line-2);font-weight:700;}
.tb tfoot td:first-child{font-weight:700;}
.tb-ctrl{font-size:9px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;
  padding:0 6px;border-radius:4px;margin-left:6px;line-height:15px;
  background:var(--tb-accent-soft);color:var(--tb-accent);white-space:nowrap;flex:none;}
tr.party > td{background:var(--tb-sunken);}
tr.party:hover > td{background:var(--tb-line-2);}
.tb-ptype{font-size:9.5px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;
  color:var(--tb-ink-3);margin-left:7px;line-height:15px;flex:none;}
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

    <div class="tb-dates">
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
        <label style="border-top:1px solid var(--tb-line);margin-top:4px;padding-top:8px">
          <input type="checkbox" id="tb-split"> ${__("Split Dr / Cr columns")}</label>
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
		$w.on("change", "#tb-pop input[type=checkbox]:not(#tb-split)", () => this.run());

		// Purely presentational — the server already sent both sides, so
		// this re-renders rather than re-running.
		$w.on("change", "#tb-split", (e) => {
			this.splitCols = $(e.currentTarget).is(":checked");
			this._renderTable();
		});

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

		$w.on("click", ".tb-lbl", (e) => {
			const $tr = $(e.currentTarget).closest("tr");
			// Inline party rows are not in data.rows, so they have no index —
			// they route from their own attributes.
			if ($tr.data("party")) return this._drillParty($tr);
			this._drill($tr.data("idx"));
		});

		let st = null;
		$w.on("input", "#tb-search", (e) => {
			clearTimeout(st);
			const v = e.target.value;
			st = setTimeout(() => {
				this.search = (v || "").toLowerCase();
				// Parties are fetched on expand, so a search has nothing to
				// match until they exist. Pull them once, then filter.
				if (this.search && !this._loadingParties) this._ensurePartiesForSearch();
				else this._renderTable();
				if (this.data) this._renderStatusBar();
			}, 200);
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

	_signed(dr, cr) {
		const net = (dr || 0) - (cr || 0);
		if (Math.abs(net) < 0.005) return `<td class="tb-nil">—</td>`;
		const isDr = net > 0;
		return `<td class="${isDr ? "tb-dr" : "tb-cr"}">${this._fmt(
			Math.abs(net)
		)}<span class="tb-sfx">${isDr ? "Dr" : "Cr"}</span></td>`;
	}

	_money(r) {
		// Four columns the Tally way, or the strict six-column split.
		return this.splitCols
			? this._cell(r.opening_debit) +
					this._cell(r.opening_credit) +
					this._cell(r.debit) +
					this._cell(r.credit) +
					this._cell(r.closing_debit, "tb-dr") +
					this._cell(r.closing_credit, "tb-cr")
			: this._signed(r.opening_debit, r.opening_credit) +
					this._cell(r.debit) +
					this._cell(r.credit) +
					this._signed(r.closing_debit, r.closing_credit);
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

		// Name the companies. The filter panel folds away after a run, so a
		// bare count leaves you unable to tell what you are looking at —
		// and two trial balances that differ only by which company was
		// selected are indistinguishable.
		const co = this.companies.map((c) => c.value);
		const expanded = (d.companies || []).length;
		let coTxt;
		if (co.length === 1) {
			// A trust expands to many, so say so rather than showing one name.
			coTxt =
				expanded > 1
					? `${co[0]} · ${expanded} ${__("companies")}`
					: co[0];
		} else if (co.length <= 3) {
			coTxt = co.join("  ·  ");
		} else {
			coTxt = `${co[0]} + ${co.length - 1} ${__("more")}`;
		}
		const fmtD = (v) => (v ? frappe.datetime.str_to_user(v) : "");
		$w.find("#tb-ctx")
			.text(
				`${coTxt}  ·  ${this.view}  ·  ${fmtD(this.filters.from_date)} → ${fmtD(
					this.filters.to_date
				)}`
			)
			// The full list is always one hover away, however many there are.
			.attr("title", (d.companies || co).join(", "));

		const pills = [];
		pills.push(
			`<span class="tb-pill dot">${
				d.source === "aggregate" ? __("Monthly aggregate") : __("Live GL")
			}${d.source_built_at ? " · " + String(d.source_built_at).slice(0, 16) : ""}</span>`
		);
		// A filter narrows the rows but not the Total — the trial balance
		// total belongs to the period, not to what you searched. Say so, or
		// 4,56,095 beside two rows adding to 40,000 reads as a contradiction.
		if (this.search)
			pills.push(
				`<span class="tb-pill warn">${__("filtered — Total is for the full period")}</span>`
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
				// A control account stays visible when the match is one of the
				// parties inside it — otherwise searching a supplier name
				// would hide the very row that contains the answer.
				if (!hay.includes(this.search) && !this._partyHit(r)) continue;
			}
			out.push(r);
		}
		return out;
	}

	_partyMatch(p) {
		if (!this.search) return true;
		return `${p.label || ""} ${p.party || ""} ${p.party_type || ""}`
			.toLowerCase()
			.includes(this.search);
	}

	_partyHit(r) {
		if (!r.is_control) return false;
		return (this.parties[r.account] || []).some((p) => this._partyMatch(p));
	}

	/* Search can only match parties it has actually fetched, and parties are
	   fetched on expand. So the first time someone searches, pull them for
	   every control account at once — there are only a handful per company,
	   and without this "search" would quietly mean "search what you happened
	   to open". */
	_ensurePartiesForSearch() {
		const rows = (this.data && this.data.rows) || [];
		const pending = rows.filter(
			(r) => r.is_control && !this.parties[r.account]
		);
		if (!pending.length) {
			this._renderTable();
			return;
		}
		this._loadingParties = true;
		this._renderTable();
		Promise.all(
			pending.map(
				(r) =>
					new Promise((resolve) => {
						frappe.call({
							method: "dux_voucher.dux_voucher.api.trial_balance.get_account_parties",
							args: {
								filters: JSON.stringify(this.filters || {}),
								accounts: JSON.stringify(r.members || [r.account]),
							},
							callback: (res) => {
								this.parties[r.account] = res.message || [];
								resolve();
							},
							error: () => {
								this.parties[r.account] = [];
								resolve();
							},
						});
					})
			)
		).then(() => {
			this._loadingParties = false;
			// Reveal what was found rather than making them expand by hand.
			(this.data.rows || []).forEach((r) => {
				if (r.is_control && this._partyHit(r)) this.partyOpen.add(r.account);
			});
			this._renderTable();
		});
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

	_partyRowHtml(p, indent, acct) {
		let name = frappe.utils.escape_html(p.label || "");
		if (p.is_unattributed) name = `<span class="tb-unatt">${name}</span>`;
		if (p.mismatch) name += `<span class="tb-flag">${__("wrong party type")}</span>`;
		const type = p.party_type
			? `<span class="tb-ptype">${frappe.utils.escape_html(p.party_type)}</span>`
			: "";
		return `<tr class="party" data-party="1" data-acct="${frappe.utils.escape_html(
			acct || ""
		)}" data-pt="${frappe.utils.escape_html(
			p.party_type || ""
		)}" data-p="${frappe.utils.escape_html(p.party || "")}">
      <td><div class="tb-name" style="padding-left:${indent + 18}px">
        <span class="tb-caret leaf">▼</span>
        <span class="tb-lbl">${name}</span>${type}
      </div></td>
      ${this._money(p)}</tr>`;
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
        ${this._money(r)}</tr>`;

				if (r.is_control && this.partyOpen.has(r.account)) {
					// When the account name itself matches, show all its parties;
					// otherwise show only the ones that matched.
					const accHit =
						!this.search ||
						`${r.account_name || ""}`.toLowerCase().includes(this.search);
					const kidsRows = (this.parties[r.account] || []).filter(
						(pp) => accHit || this._partyMatch(pp)
					);
					// Across a trust the row is a merge key, not an account —
					// hand the drill a real account name to open.
					const realAcct = (r.members && r.members[0]) || r.account;
					html += kidsRows.map((p) => this._partyRowHtml(p, indent, realAcct)).join("");
					if (!kidsRows.length) {
						html += `<tr class="party"><td colspan="${
							this.splitCols ? 7 : 5
						}" style="padding-left:${
							indent + 36
						}px;color:var(--tb-ink-3);font-style:italic">${__(
							"No parties on this account for the period."
						)}</td></tr>`;
					}
				}
				return html;
			})
			.join("");

		if (this._loadingParties) {
			$r.find(".tb-tablewrap").before(
				`<div class="tb-searching">${__("Loading parties to search…")}</div>`
			);
		}
		const tot = rows.find((r) => r.is_total);
		// In the four-column view Opening and Closing are netted, so the
		// Total's netted figure is the Dr/Cr difference -- which is the tie
		// check, not a sum. Say so, or 2,375.32 sitting under a column of
		// crores reads as a broken total. Debit and Credit stay true sums,
		// so the tie is still visible in the row itself.
		const totLabel = this.splitCols ? __("Total") : __("Total (net)");
		const totHint = this.splitCols
			? ""
			: ` title="${__(
					"Opening and Closing are netted, so their totals show the Dr − Cr difference. Debit and Credit are true column sums."
			  )}"`;
		const foot = tot
			? `<tfoot><tr>
          <td${totHint}>${totLabel}</td>
          ${this._money(tot)}
        </tr></tfoot>`
			: "";

		$r.html(`<div class="tb-tablewrap"><table class="tb ${
			this.splitCols ? "" : "cols4"
		}">
      <thead><tr>
        <th>${first}</th>
        ${
					this.splitCols
						? `<th>${__("Opening (Dr)")}</th><th>${__("Opening (Cr)")}</th>
             <th>${__("Debit")}</th><th>${__("Credit")}</th>
             <th>${__("Closing (Dr)")}</th><th>${__("Closing (Cr)")}</th>`
						: `<th>${__("Opening")}</th><th>${__("Debit")}</th>
             <th>${__("Credit")}</th><th>${__("Closing")}</th>`
				}
      </tr></thead><tbody>${body}</tbody>${foot}</table></div>`);

		if (keepTop) $r.find(".tb-tablewrap").scrollTop(keepTop);
	}

	_openLedger(route, opts) {
		// A new tab, so the trial balance you were reading stays put. Route
		// options live in memory and do not survive a fresh document, so the
		// context travels in the query string; both ledger pages read it.
		const qs = Object.keys(opts)
			.filter((k) => opts[k])
			.map((k) => encodeURIComponent(k) + "=" + encodeURIComponent(opts[k]))
			.join("&");
		window.open(`/desk/${route}?${qs}`, "_blank");
	}

	_drillParty($tr) {
		const acct = $tr.data("acct");
		const party = $tr.data("p");
		const party_type = $tr.data("pt");
		const f = this.filters || {};
		if (!party) {
			// The Unattributed row has no party to open; the account ledger
			// is the honest destination, since that is where it lives.
			if (!acct) return;
			this._openLedger("dux-ledger", {
				company: (this.data.companies || [])[0],
				account: acct,
				from_date: f.from_date,
				to_date: f.to_date,
			});
			return;
		}
		// The account tells us its company, which matters once a trust is
		// selected and the row merged several companies together.
		frappe.db.get_value("Account", acct, "company").then((r) => {
			this._openLedger("dux-party-ledger", {
				company: (r && r.message && r.message.company) || (this.data.companies || [])[0],
				party: party,
				party_type: party_type,
				account: acct,
				from_date: f.from_date,
				to_date: f.to_date,
			});
		});
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
		const base = frappe.route_options;
		if (r.party) {
			this._openLedger("dux-party-ledger", {
				...base,
				party: r.party,
				party_type: r.party_type,
				account: r.parent_account || r.account,
			});
		} else if (!r.is_group_account) {
			this._openLedger("dux-ledger", { ...base, account: r.account });
		}
	}

	_excel() {
		if (!this.data) {
			frappe.show_alert({ message: __("Run the report first."), indicator: "orange" });
			return;
		}
		// Same execute() the screen ran, formatted server-side, streamed
		// back as a file — not a detour through the classic report.
		const url =
			"/api/method/dux_voucher.dux_voucher.api.reports_export.export_trial_balance_xlsx" +
			"?filters=" +
			encodeURIComponent(JSON.stringify(this.filters || {}));
		frappe.show_alert({ message: __("Building the workbook…"), indicator: "blue" });
		// Same mechanism as the other Excel buttons in this app: a
		// Content-Disposition download, so the browser saves the file
		// without navigating away and without leaving a blank tab behind.
		window.location.href = url;
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
