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
		// What ``data`` answers: the filters, view and selection of the run
		// that produced it. Labels and drills read these, never the newest ask.
		this._ran = null;
		this.search = "";
		this.parties = {}; // account key -> party rows, fetched on demand
		this.partyOpen = new Set();
		// Tally shows Opening and Closing as one signed column each. The
		// split Dr/Cr form is available for anyone who wants the strict
		// six-column presentation.
		this.splitCols = false;
		// With two or more companies: one column per company beside the
		// consolidated figure, showing one figure at a time. ``coChoice`` is
		// what the user picked on the switch above the table (null until they
		// do); ``coAll`` lifts the row cap for this run.
		this.coFig = "closing";
		this.coChoice = null;
		this.coAll = false;

		this._styles();
		this._layout();
		this._bind();
		this._defaults();
		this._syncOptions();
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
/* Fade the dash, not the cell: opacity on the cell also faded its background,
   so the pinned Total's nil cells showed the rows scrolling underneath. */
.tb-nil{color:color-mix(in srgb,var(--tb-ink-3) 50%,transparent);}
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
.tb-tie.net{background:var(--tb-sunken);color:var(--tb-ink-2);}
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
.tb-pop label.off{opacity:.45;cursor:not-allowed;}
.tb-pop label.tb-sub{padding-left:24px;}
.tb-pop select{height:28px;border:1px solid var(--tb-line);border-radius:6px;
  background:var(--tb-bg);color:var(--tb-ink);font-size:12.5px;padding:0 6px;
  font-family:inherit;}

/* Company columns: the account and the consolidated Total pinned on the
   left, one column per company to their right, scrolling sideways. Pinned
   cells need an opaque background or the scrolled figures show through. */
.tb-costrip{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  margin:-2px 0 10px;font-size:12px;color:var(--tb-ink-3);}
.tb-costrip .tb-seg button{font-size:12px;padding:4px 11px;}
.tb-costrip .lbl{font-size:10.5px;font-weight:700;letter-spacing:.08em;
  text-transform:uppercase;}
.tb-costrip .note{cursor:help;}
table.tb.coc{table-layout:auto;width:max-content;min-width:100%;}
table.tb.coc td,table.tb.coc th{background:var(--tb-bg);}
table.tb.coc th:first-child,table.tb.coc td:first-child{width:auto;position:sticky;
  left:0;z-index:1;border-right:1px solid var(--tb-line);}
table.tb.coc .tb-name{width:300px;}
table.tb.coc th:not(:first-child),table.tb.coc td:not(:first-child){width:auto;
  min-width:150px;}
table.tb.coc .tb-cot{position:sticky;left:var(--tb-c1w,325px);z-index:1;
  font-weight:650;border-right:1px solid var(--tb-line);}
table.tb.coc thead th{white-space:nowrap;background:var(--tb-sunken);}
table.tb.coc thead th:first-child,table.tb.coc thead th.tb-cot{z-index:5;}
table.tb.coc tfoot td:first-child,table.tb.coc tfoot td.tb-cot{z-index:5;}
table.tb.coc tbody tr:hover td{background:var(--tb-sunken);}
table.tb.coc tr.party > td{background:var(--tb-sunken);}
table.tb.coc thead th[title]{cursor:help;}
.tb-figtag{font-weight:600;color:var(--tb-accent);margin-left:6px;}
td.tb-coc{cursor:pointer;}
td.tb-coc:hover{text-decoration:underline;}
tr.tb-cap td{text-align:left;color:var(--tb-ink-3);font-style:italic;padding:9px 14px;}
tr.tb-cap a{font-style:normal;font-weight:600;cursor:pointer;}
.tb-tie.warn{background:var(--tb-warn-soft);color:var(--tb-warn);}
.tb-pick-row{display:flex;justify-content:space-between;gap:16px;padding:5px 0;
  border-bottom:1px solid var(--tb-line-2);}
.tb-printonly{display:none;}
@media print{
  .tb-tablewrap{max-height:none;overflow:visible;}
  /* The controls stay on screen. What was run (companies, view, dates,
     source, tie, the filter and its caveat, the companies left out of the
     columns) prints above the table; the figure shown is already in the
     first column's heading. */
  .tb-filters,#tb-coseg,#tb-figseg,.tb-costrip .lbl,#tb-search,.tb-bar .tb-popwrap,#tb-edit{
    display:none !important;}
  .tb-printonly{display:inline;}
  .tb-bar{flex-wrap:wrap;}
  .tb-bar .ctx{max-width:none;overflow:visible;white-space:normal;}
}
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
        <label id="tb-net-l"><input type="checkbox" id="tb-net" checked> ${__("Net opening / closing")}</label>
        <label><input type="checkbox" id="tb-grp" checked> ${__("Group accounts")}</label>
        <label><input type="checkbox" id="tb-zero"> ${__("Zero rows")}</label>
        <label><input type="checkbox" id="tb-pl"> ${__("Carry prior-year P&L")}</label>
        <label><input type="checkbox" id="tb-live"> ${__("Force live query")}</label>
        <label id="tb-split-l"><input type="checkbox" id="tb-split"> ${__("Split Dr / Cr columns")}</label>
      </div>
    </span>
    <button class="tb-mini" id="tb-edit">${__("Filters")}</button>
  </div>

  <div class="tb-costrip" id="tb-costrip" style="display:none">
    <span class="lbl">${__("Companies")}</span>
    <span class="tb-seg" id="tb-coseg">
      <button data-co="0">${__("Combined")}</button>
      <button data-co="1">${__("By company")}</button>
    </span>
    <span class="tb-seg" id="tb-figseg">
      <button data-fig="closing">${__("Closing")}</button>
      <button data-fig="opening">${__("Opening")}</button>
      <button data-fig="debit">${__("Debit")}</button>
      <button data-fig="credit">${__("Credit")}</button>
    </span>
    <span class="note" id="tb-conote"></span>
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
			// Once anything has run, a view picked is run at once. With no
			// company to run it for it is not taken, as Run refuses: the
			// table on screen keeps its view, and the pills keep naming it.
			if (this._seq && !this.companies.length) {
				frappe.show_alert({ message: __("Pick a company or a trust first."), indicator: "orange" });
				return;
			}
			this.view = $(e.currentTarget).data("view");
			$w.find("#tb-seg button").removeClass("on");
			$(e.currentTarget).addClass("on");
			this._syncOptions();
			// Once anything has run, the first run included: a view picked
			// while it is out is what is asked for, not the one it answers.
			if (this._seq) this.run();
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

		// Combined, or a column per company. The server computes the company
		// figures only when asked, so switching re-runs.
		$w.on("click", "#tb-coseg button", (e) => {
			const on = String($(e.currentTarget).data("co")) === "1";
			// Against what was last asked for: while a run is out, the table
			// on screen is the previous one. After a run failed, the same
			// position asks again.
			if (on === this._coAsked() && this._failedSeq !== this._seq) return;
			this.coChoice = on;
			this.run();
		});

		// Which figure the company columns show. Every figure came back with
		// the run, so this only re-renders.
		$w.on("click", "#tb-figseg button", (e) => {
			this.coFig = String($(e.currentTarget).data("fig")) || "closing";
			this._syncOptions();
			this._renderTable();
			this._renderStatusBar();
		});

		$w.on("click", ".tb-showall", (e) => {
			e.preventDefault();
			this.coAll = true;
			this._renderTable();
		});

		// A company's figure opens THAT company's ledger. The row itself
		// merges the same account across companies, so it names no single
		// ledger to open.
		$w.on("click", "td.tb-coc", (e) => {
			const $td = $(e.currentTarget);
			const $tr = $td.closest("tr");
			const ci = Number($td.data("ci"));
			if (!Number.isInteger(ci)) return;
			if ($tr.data("party")) return this._drillPartyCo($tr, ci);
			this._drillCo($tr.data("idx"), ci);
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
		this.page.add_menu_item(__("Print"), () => this._print());
		this.page.add_menu_item(__("Rebuild aggregate"), () => this._rebuild());
		this.page.add_menu_item(__("Open as classic report"), () => this._classic());
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
		this._syncOptions();
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
			company_columns: this._coWanted() ? 1 : 0,
		};
		this.filters = filters;
		this.coAll = false;
		// Each run is numbered. An answer to an earlier run that lands after a
		// later one was asked for is dropped, so the table never shows a
		// selection, a view or a switch position that is no longer asked.
		const seq = (this._seq = (this._seq || 0) + 1);
		// Kept with the answer: chips added while the run is out are not
		// what it ran.
		const ran = {
			filters,
			view: this.view,
			sel: this._selKey(),
			companies: this.companies.map((c) => c.value),
		};
		this._syncOptions();

		$w.find("#tb-result").html(`<div class="tb-empty">${__("Running…")}</div>`);
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.get_trial_balance",
			args: { filters: JSON.stringify(filters) },
			callback: (r) => {
				if (seq !== this._seq) return;
				this.data = r.message;
				this._ran = ran;
				this._dataSeq = seq;
				this._coShownCache = null;
				this.collapsed = new Set();
				this.parties = {};
				this.partyOpen = new Set();
				// A party load still out belongs to the table this replaces.
				this._loadingParties = false;
				// Filters are a set-up step, not a thing you stare at. Fold
				// them away once there is a report to look at.
				$w.find(".tb-filters").hide();
				$w.find("#tb-bar").css("display", "flex");
				this._syncOptions();
				this._renderStatusBar();
				// The row filter outlives the run, and it can match a party
				// only once it is fetched: this table starts with none.
				if (this.search) this._ensurePartiesForSearch();
				else this._renderTable();
			},
			error: () => {
				if (seq !== this._seq) return;
				this._failedSeq = seq;
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
		// One formatter for the page: building one per cell was most of the
		// render time once a trust's companies each got a column.
		if (!this._nf)
			this._nf = new Intl.NumberFormat("en-IN", {
				minimumFractionDigits: 2,
				maximumFractionDigits: 2,
			});
		return this._nf.format(v);
	}

	_signed(dr, cr) {
		const net = (dr || 0) - (cr || 0);
		if (Math.abs(net) < 0.005) return `<td class="tb-nil">—</td>`;
		const isDr = net > 0;
		return `<td class="${isDr ? "tb-dr" : "tb-cr"}">${this._fmt(
			Math.abs(net)
		)}<span class="tb-sfx">${isDr ? "Dr" : "Cr"}</span></td>`;
	}

	/* -------------------------------------------------- company columns */
	_selKey() {
		return JSON.stringify(this.companies.map((c) => c.value));
	}

	_coColsApplicable() {
		// Two or more companies, and a view whose rows are shared across
		// companies: Account → Party lists each company's own accounts and By
		// Company is already one row per company. Once the selection has run,
		// count what it resolved to — a trust can hold a single company.
		const ran = this.data && this._ran && this._ran.sel === this._selKey();
		const many = ran
			? (this.data.companies || []).length > 1
			: this.companies.length > 1 || this.companies.some((c) => c.is_group);
		return many && (this.view === "By Account" || this.view === "By Party");
	}

	_coWanted() {
		if (!this._coColsApplicable()) return false;
		if (this.coChoice !== null) return this.coChoice;
		// Colleges picked by hand are picked to be set side by side; a trust
		// is first its consolidated trial balance. Either is one click away.
		const handPicked = !this.companies.some((c) => c.is_group);
		return handPicked && this.companies.length <= 6;
	}

	_coMode() {
		const d = this.data;
		return !!(d && d.company_columns && (d.companies || []).length > 1);
	}

	// Where the Combined / By company switch stands: what the table on screen
	// shows, or, while a run is out or after one failed, what that run asked
	// for. A click compared with the table alone was lost while a run was out.
	_coAsked() {
		if (this.filters && this._dataSeq !== this._seq) return !!this.filters.company_columns;
		return this._coMode();
	}

	// The filters behind the table on screen. A drill or a party load is for
	// that table's period and companies, not for an ask still out or failed.
	_ranFilters() {
		return (this._ran && this._ran.filters) || this.filters || {};
	}

	// Indexes of the companies with any figure in this run. A college with
	// nothing on the selected project, cost centre or period is a column of
	// dashes; it is left out and named in the note instead.
	_coShown() {
		if (this._coShownCache) return this._coShownCache;
		const d = this.data || {};
		const n = (d.companies || []).length;
		const has = new Array(n).fill(false);
		for (const r of d.rows || []) {
			(r.cv || []).forEach((c, i) => {
				if (c) has[i] = true;
			});
		}
		this._coShownCache = has.map((h, i) => (h ? i : -1)).filter((i) => i >= 0);
		return this._coShownCache;
	}

	_abbr(i) {
		const d = this.data || {};
		const c = (d.companies || [])[i];
		return (d.company_abbrs || {})[c] || c;
	}

	_syncOptions() {
		const $w = $(this.wrapper);
		const ok = this._coColsApplicable();
		const asked = this._coAsked();
		// The figure picker and its note describe the table on screen, so they
		// show only once that table is the one asked for: not while a run is
		// out, nor after one failed and left no table.
		const on = this._dataSeq === this._seq && this._coMode() && asked;
		const d = this.data || {};
		$w.find("#tb-costrip").css("display", d.rows && ok ? "flex" : "none");
		$w.find("#tb-coseg button").each((i, b) => {
			$(b).toggleClass("on", String($(b).data("co")) === (asked ? "1" : "0"));
		});
		$w.find("#tb-figseg").toggle(on);
		$w.find("#tb-figseg button").each((i, b) => {
			$(b).toggleClass("on", $(b).data("fig") === this.coFig);
		});
		let note = "";
		let title = "";
		if (on) {
			const shown = this._coShown();
			const n = (d.companies || []).length;
			const hidden = (d.companies || []).filter((c, i) => !shown.includes(i));
			if (hidden.length) {
				note = __("{0} of {1} companies have nothing in this run and are not shown", [
					hidden.length,
					n,
				]);
				title = hidden.join(", ");
			}
		}
		// The names are a hover away on screen; a printout names them.
		const esc = frappe.utils.escape_html;
		$w.find("#tb-conote")
			.html(note ? `${esc(note)}<span class="tb-printonly">: ${esc(title)}</span>` : "")
			.attr("title", title);
		// Splitting Dr and Cr would double every company column, and every
		// company cell is already one signed figure, netted or not. These
		// follow the switch, so they change the moment it is pushed.
		$w.find("#tb-split").prop("disabled", asked);
		$w.find("#tb-split-l")
			.toggleClass("off", asked)
			.attr("title", asked ? __("Not available with a column per company") : "");
		$w.find("#tb-net").prop("disabled", asked);
		$w.find("#tb-net-l")
			.toggleClass("off", asked)
			.attr(
				"title",
				asked ? __("Each company's opening and closing already show as one Dr or Cr figure") : ""
			);
	}

	_figLabel() {
		return (
			{ closing: __("Closing"), opening: __("Opening"), debit: __("Debit"), credit: __("Credit") }[
				this.coFig
			] || __("Closing")
		);
	}

	_signedFig() {
		return this.coFig === "opening" || this.coFig === "closing";
	}

	// One figure from the six values [opening Dr, opening Cr, Dr, Cr, closing
	// Dr, closing Cr]: Opening and Closing as one signed figure, debit
	// positive; Debit and Credit as they are.
	_coVal(v) {
		if (!v) return 0;
		if (this.coFig === "opening") return (v[0] || 0) - (v[1] || 0);
		if (this.coFig === "closing") return (v[4] || 0) - (v[5] || 0);
		return (this.coFig === "debit" ? v[2] : v[3]) || 0;
	}

	_coFmt(v) {
		const x = this._coVal(v);
		if (Math.abs(x) < 0.005) return null;
		if (!this._signedFig()) return { html: this._fmt(x), tone: "" };
		return {
			html: `${this._fmt(Math.abs(x))}<span class="tb-sfx">${x > 0 ? "Dr" : "Cr"}</span>`,
			tone: x > 0 ? "tb-dr" : "tb-cr",
		};
	}

	_coTd(v, cls, attrs) {
		const f = this._coFmt(v);
		if (!f) return `<td class="tb-nil ${cls || ""}">—</td>`;
		return `<td class="${f.tone} ${cls || ""}"${attrs || ""}>${f.html}</td>`;
	}

	// The consolidated Total first, pinned beside the name, then one cell per
	// company with a figure in this run.
	_coCells(r, clickable) {
		const cv = r.cv || [];
		const own = [
			r.opening_debit,
			r.opening_credit,
			r.debit,
			r.credit,
			r.closing_debit,
			r.closing_credit,
		];
		let html = this._coTd(own, "tb-cot");
		for (const i of this._coShown()) {
			// Only a figure opens a ledger. A company can hold the row and
			// still show a dash for this figure (an income head's opening):
			// that dash is not a link.
			const f = this._coFmt(cv[i]);
			if (!f) html += `<td class="tb-nil">—</td>`;
			else if (clickable) html += `<td class="${f.tone} tb-coc" data-ci="${i}">${f.html}</td>`;
			else html += `<td class="${f.tone}">${f.html}</td>`;
		}
		return html;
	}

	// Each company's own difference, from the Total row: what the badge and the
	// bottom row report company by company.
	_coOut() {
		const tot = ((this.data || {}).rows || []).find((r) => r.is_total);
		const out = [];
		((tot && tot.cv) || []).forEach((c, i) => {
			const diff = c ? (c[4] || 0) - (c[5] || 0) : 0;
			if (Math.abs(diff) >= 0.005) out.push({ i, diff });
		});
		return out;
	}

	_money(r, clickable) {
		if (this._coMode()) return this._coCells(r, clickable);
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
		// What the figures are for: the run that produced them, not chips,
		// a view or dates picked since.
		const ran = this._ran || {};
		const rf = this._ranFilters();

		// Name the companies. The filter panel folds away after a run, so a
		// bare count leaves you unable to tell what you are looking at —
		// and two trial balances that differ only by which company was
		// selected are indistinguishable.
		const co = ran.companies || this.companies.map((c) => c.value);
		const expanded = (d.companies || []).length;
		const esc = frappe.utils.escape_html;
		let coTxt;
		if (co.length === 1) {
			// A trust expands to many, so say so rather than showing one name.
			coTxt = esc(expanded > 1 ? `${co[0]} · ${expanded} ${__("companies")}` : co[0]);
		} else if (co.length <= 3) {
			coTxt = esc(co.join("  ·  "));
		} else {
			// The rest are a hover away on screen; a printout names them.
			coTxt = `${esc(`${co[0]} + ${co.length - 1} ${__("more")}`)}<span class="tb-printonly">: ${esc(
				co.slice(1).join(", ")
			)}</span>`;
		}
		const fmtD = (v) => (v ? frappe.datetime.str_to_user(v) : "");
		$w.find("#tb-ctx")
			.html(
				`${coTxt}  ·  ${esc(
					`${ran.view || this.view}  ·  ${fmtD(rf.from_date)} → ${fmtD(rf.to_date)}`
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
		// The filter box is not printed, so a printout names the filter.
		if (this.search)
			pills.push(
				`<span class="tb-pill warn"><span class="tb-printonly">“${frappe.utils.escape_html(
					String($w.find("#tb-search").val() || "").trim()
				)}” · </span>${__("filtered — Total is for the full period")}</span>`
			);

		const mism = rows.filter((r) => r.mismatch).length;
		if (mism) pills.push(`<span class="tb-pill warn">${mism} ${__("mismatch")}</span>`);
		const unatt = rows.filter((r) => r.is_unattributed).length;
		if (unatt) pills.push(`<span class="tb-pill warn">${unatt} ${__("unattributed")}</span>`);
		// By Company folds each company's carry-forward into its own row.
		if (rows.find((r) => r.is_computed || r.carry_forward))
			pills.push(`<span class="tb-pill warn">${__("computed carry-forward")}</span>`);
		$w.find("#tb-pills").html(pills.join(""));

		if (total) {
			const diff = (total.closing_debit || 0) - (total.closing_credit || 0);
			const tied = Math.abs(diff) < 0.005;
			// Most of a ledger has no party, so a list of parties never ties:
			// its total is where the parties stand on balance, not an error.
			// Judged by the view the figures were built for, not the button.
			if ((d.view || this.view) === "By Party") {
				$w.find("#tb-tie").html(
					`<span class="tb-tie net">${__("Net of parties")} ${
						tied ? __("nil") : this._fmt(Math.abs(diff)) + (diff > 0 ? " Dr" : " Cr")
					}</span>`
				);
			} else if (this._coMode()) {
				// The consolidated tie can hide two colleges out by opposite
				// amounts — exactly what a column per company is there to show,
				// so the badge reads company by company too.
				const n = (d.companies || []).length;
				const out = this._coOut();
				const who = out
					.map((o) => {
						const x = this._fmt(Math.abs(o.diff)) + (o.diff > 0 ? " Dr" : " Cr");
						return `${(d.companies || [])[o.i]}: ${x}`;
					})
					.join("\n");
				const names = out.slice(0, 3).map((o) => this._abbr(o.i));
				const more = out.length > 3 ? ` +${out.length - 3}` : "";
				let cls, txt;
				if (tied && !out.length) {
					cls = "ok";
					txt = "✓ " + __("Balanced · all {0} companies tie", [n]);
				} else if (tied) {
					cls = "warn";
					txt =
						"✓ " +
						__("Balanced overall · {0} of {1} out ({2})", [
							out.length,
							n,
							names.join(", ") + more,
						]);
				} else {
					cls = "off";
					txt =
						"⚠ " +
						__("Out by") +
						" " +
						this._fmt(diff) +
						(out.length ? " · " + __("{0} of {1} companies out", [out.length, n]) : "");
				}
				$w.find("#tb-tie").html(
					`<span class="tb-tie ${cls}" title="${frappe.utils.escape_html(who)}">${frappe.utils.escape_html(
						txt
					)}</span>`
				);
			} else {
				$w.find("#tb-tie").html(
					`<span class="tb-tie ${tied ? "ok" : "off"}">${
						tied ? "✓ " + __("Balanced") : "⚠ " + __("Out by") + " " + this._fmt(diff)
					}</span>`
				);
			}
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
		// For the table on screen: a run landing meanwhile resets the
		// parties, and these would carry the earlier run's period, and its
		// companies' columns, into the new one.
		const seq = this._dataSeq;
		const filters = JSON.stringify(this._ranFilters());
		this._loadingParties = true;
		this._renderTable();
		Promise.all(
			pending.map(
				(r) =>
					new Promise((resolve) => {
						frappe.call({
							method: "dux_voucher.dux_voucher.api.trial_balance.get_account_parties",
							args: {
								filters,
								accounts: JSON.stringify(r.members || [r.account]),
							},
							callback: (res) => {
								if (seq === this._dataSeq) this.parties[r.account] = res.message || [];
								resolve();
							},
							// Not kept as "no parties": the next keystroke asks again.
							error: () => resolve(),
						});
					})
			)
		).then(() => {
			if (seq !== this._dataSeq) return;
			this._loadingParties = false;
			// Reveal what was found rather than making them expand by hand:
			// for the filter now in the box. Cleared while these loaded, every
			// party would match, and every control account would open.
			if (this.search)
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
		const seq = this._dataSeq;
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.get_account_parties",
			args: {
				filters: JSON.stringify(this._ranFilters()),
				accounts: JSON.stringify(row.members || [row.account]),
			},
			callback: (r) => {
				// Dropped once another run has landed: it was for that table.
				if (seq !== this._dataSeq) return;
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

	_partyRowHtml(p, indent, acct, ridx) {
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
		)}" data-p="${frappe.utils.escape_html(p.party || "")}" data-ridx="${ridx}">
      <td><div class="tb-name" style="padding-left:${indent + 18}px">
        <span class="tb-caret leaf">▼</span>
        <span class="tb-lbl">${name}</span>${type}
      </div></td>
      ${this._money(p, true)}</tr>`;
	}

	_renderTable() {
		// While a run is out, or after one failed, what is in hand answers an
		// earlier ask. The figure picker, Split, the filter box and a late
		// party load all redraw; none may put that table back under the new
		// ask's labels in place of "Running…" or "Could not run".
		if (this._dataSeq !== this._seq) return;
		const d = this.data || {};
		const rows = d.rows || [];
		const $r = $(this.wrapper).find("#tb-result");
		// Expanding a row re-renders the whole table, which destroys the
		// scroller and sends you back to the top. Carry the offset across.
		const keepTop = $r.find(".tb-tablewrap").scrollTop() || 0;
		const keepLeft = $r.find(".tb-tablewrap").scrollLeft() || 0;
		if (!rows.length) {
			$r.html(
				`<div class="tb-empty"><strong>${__("No rows")}</strong>${__(
					"Nothing matched this period."
				)}</div>`
			);
			return;
		}

		// The view the table answers, not a pill picked since.
		const view = d.view || this.view;
		const isParty = view === "By Party";
		const isCo = view === "By Company";
		const first = isParty ? __("Party") : isCo ? __("Company") : __("Account");
		const coMode = this._coMode();

		const kids = new Set(rows.map((r) => r.parent_account).filter(Boolean));
		let vis = this._visible(rows);
		// A trust's By Party can run to thousands of parties with a cell per
		// company each. Draw a bounded number of cells and offer the rest,
		// rather than freeze the tab on every keystroke in the filter box.
		let capped = 0;
		if (coMode && !this.coAll) {
			const max = Math.max(400, Math.floor(60000 / (this._coShown().length + 1)));
			if (vis.length > max) {
				capped = vis.length;
				vis = vis.slice(0, max);
			}
		}

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
        ${this._money(r, !r.is_group_account && !r.is_computed)}</tr>`;

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
					html += kidsRows
						.map((p) => this._partyRowHtml(p, indent, realAcct, idx))
						.join("");
					if (!kidsRows.length) {
						html += `<tr class="party"><td colspan="${
							coMode ? this._coShown().length + 2 : this.splitCols ? 7 : 5
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
		const capRow = capped
			? `<tr class="tb-cap"><td colspan="${this._coShown().length + 2}">${__(
					"Showing {0} of {1} rows.",
					[vis.length, capped]
			  )} <a class="tb-showall">${__("Show all")}</a> · ${__(
					"or narrow them with the filter box. The Excel workbook has every row."
			  )}</td></tr>`
			: "";

		// Drawn with the table: put in before it, the redraw below wiped it.
		// Not once the filter is cleared: nothing is being searched.
		const searching =
			this._loadingParties && this.search
				? `<div class="tb-searching">${__("Loading parties to search…")}</div>`
				: "";
		const tot = rows.find((r) => r.is_total);
		// In the four-column view Opening and Closing are netted, so the
		// Total's netted figure is the Dr/Cr difference -- which is the tie
		// check, not a sum. Say so, or 2,375.32 sitting under a column of
		// crores reads as a broken total. Debit and Credit stay true sums,
		// so the tie is still visible in the row itself.
		let totLabel, totHint;
		if (coMode) {
			// What the bottom row is depends on the figure and the view: a
			// company's difference (nil when it ties) for Opening and Closing by
			// account, where its parties stand on balance by party, and plain
			// sums for Debit and Credit.
			const signed = this._signedFig();
			if (isParty) {
				totLabel = signed ? __("Net of parties") : __("Total");
				totHint = signed
					? __(
							"Each company's parties, netted. Most of a ledger has no party, so this is where the parties stand, not a tie check."
					  )
					: __("True sums: each company's figure, and in Total all of them together.");
			} else {
				totLabel = signed ? __("Difference") : __("Total");
				totHint = signed
					? __(
							"Each company's debit less its credit: nil when that company's books tie. The Total column is the consolidated difference the badge checks."
					  )
					: __("True sums: each company's figure, and in Total all of them together.");
			}
		} else {
			// In the four-column view Opening and Closing are netted, so the
			// Total's netted figure is the Dr/Cr difference -- which is the tie
			// check, not a sum. Say so, or 2,375.32 sitting under a column of
			// crores reads as a broken total. Debit and Credit stay true sums,
			// so the tie is still visible in the row itself.
			const netted = !this.splitCols;
			totLabel = netted ? __("Total (net)") : __("Total");
			totHint = netted
				? __(
						"Opening and Closing are netted, so their totals show the Dr − Cr difference. Debit and Credit are true column sums."
				  )
				: "";
		}
		const foot = tot
			? `<tfoot><tr>
          <td${totHint ? ` title="${frappe.utils.escape_html(totHint)}"` : ""}>${totLabel}</td>
          ${this._money(tot)}
        </tr></tfoot>`
			: "";

		const coHead = () =>
			`<th class="tb-cot" title="${frappe.utils.escape_html(
				__("All the companies together — the figure the badge checks")
			)}">${__("Total")}</th>` +
			this._coShown()
				.map(
					(i) =>
						`<th title="${frappe.utils.escape_html(
							(d.companies || [])[i]
						)}">${frappe.utils.escape_html(this._abbr(i))}</th>`
				)
				.join("");

		$r.html(`${searching}<div class="tb-tablewrap"><table class="tb ${
			coMode ? "coc" : this.splitCols ? "" : "cols4"
		}">
      <thead><tr>
        <th>${first}${
			coMode ? `<span class="tb-figtag">· ${frappe.utils.escape_html(this._figLabel())}</span>` : ""
		}</th>
        ${
					coMode
						? coHead()
						: this.splitCols
						? `<th>${__("Opening (Dr)")}</th><th>${__("Opening (Cr)")}</th>
             <th>${__("Debit")}</th><th>${__("Credit")}</th>
             <th>${__("Closing (Dr)")}</th><th>${__("Closing (Cr)")}</th>`
						: `<th>${__("Opening")}</th><th>${__("Debit")}</th>
             <th>${__("Credit")}</th><th>${__("Closing")}</th>`
				}
      </tr></thead><tbody>${body}${capRow}</tbody>${foot}</table></div>`);

		if (coMode) {
			// The Total column is pinned just right of the name column, whose
			// width depends on the font and the padding at this screen size.
			const $t = $r.find("table.tb");
			const w = $t.find("thead th:first-child").outerWidth();
			if (w) $t[0].style.setProperty("--tb-c1w", `${w}px`);
		}
		if (keepTop) $r.find(".tb-tablewrap").scrollTop(keepTop);
		if (keepLeft) $r.find(".tb-tablewrap").scrollLeft(keepLeft);
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
		const f = this._ranFilters();
		// The control row above may merge one account across several
		// companies. With a column per company the party's own figures say
		// which company to open; combined, they cannot.
		const r = (this.data.rows || [])[$tr.data("ridx")];
		if (r && this._coMode()) {
			const p = (this.parties[r.account] || []).find(
				(x) =>
					(x.party_type || "") === String(party_type || "") &&
					(x.party || "") === String(party || "")
			);
			const has = ((p && p.cv) || []).map((c, i) => (c ? i : -1)).filter((i) => i >= 0);
			if (has.length === 1) return this._drillPartyCo($tr, has[0]);
			if (has.length > 1)
				return this._chooseCo(has, p.cv, (ci) => this._drillPartyCo($tr, ci));
			return;
		}
		const spans = new Set((r && r.member_companies) || []).size;
		if (spans > 1) {
			frappe.show_alert({
				message: __(
					"This account adds up {0} companies. Choose By company above the table, then click a company's figure to open its ledger.",
					[spans]
				),
				indicator: "blue",
			});
			return;
		}
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
		const f = this._ranFilters();
		const cos = this.data.companies || [];
		const view = this.data.view || this.view;
		// Across companies a By Account row is a merge key, not an account: it
		// names no ledger. With company columns, a row that only one company
		// has opens that company's; otherwise each company's figure is the
		// way in. (Account → Party lists real accounts and keeps its drill.)
		const merged = view === "By Account" || view === "By Party";
		if (merged && cos.length > 1 && !r.is_group_account) {
			if (this._coMode()) {
				const has = cos.map((c, i) => i).filter((i) => (r.cv || [])[i]);
				if (has.length === 1) return this._drillCo(idx, has[0]);
				if (has.length > 1) return this._chooseCo(has, r.cv, (ci) => this._drillCo(idx, ci));
				return;
			}
			// Combined, the row adds up the companies that hold it — a party's
			// too — so it names no single ledger. Opening the first company's
			// read as a nil balance wherever the row lived in another one. A
			// control account knows its companies: held by one, it opens that
			// one's ledger. Any other row cannot say how many it adds up.
			const spans = [...new Set(r.member_companies || [])];
			if (spans.length === 1 && cos.includes(spans[0])) return this._drillCo(idx, cos.indexOf(spans[0]));
			frappe.show_alert({
				message:
					spans.length > 1
						? __(
								"This row adds up {0} companies. Choose By company above the table, then click a company's figure to open its ledger.",
								[spans.length]
						  )
						: __(
								"This row can add up several companies. Choose By company above the table, then click a company's figure to open its ledger."
						  ),
				indicator: "blue",
			});
			return;
		}
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

	/* One company's ledger for a row, from that company's column. */
	_drillCo(idx, ci) {
		const r = (this.data.rows || [])[idx];
		const co = (this.data.companies || [])[ci];
		if (!r || !co || r.is_total || r.is_computed || r.is_group_account) return;
		const f = this._ranFilters();
		const base = { company: co, from_date: f.from_date, to_date: f.to_date };
		if (r.party) return this._openParty(base, r);
		// A control account already carries its real accounts and their
		// companies; any other row asks which account this company holds
		// under the merged one.
		const own = this._ownAccounts(r, co);
		if (own.length) return this._openOwn(base, own);
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.get_company_accounts",
			// The run's companies, in order, rebuild the run's own row keys.
			args: { company: co, key: r.account, companies: JSON.stringify(this.data.companies || []) },
			callback: (res) => this._openOwn(base, res.message || []),
		});
	}

	/* A By Party row names a party but no account, and the Party Ledger loads
	   only with one: the account the party's lines sit on in that company.
	   Its figures are the party's own whichever account heads them. */
	_openParty(base, r) {
		frappe.call({
			method: "dux_voucher.dux_voucher.api.trial_balance.get_party_account",
			args: { company: base.company, party_type: r.party_type, party: r.party },
			callback: (res) => {
				if (!res.message) {
					// An alert reads HTML, and these are names people typed.
					frappe.show_alert({
						message: __("{0} has no ledger lines for {1}.", [
							frappe.utils.escape_html(base.company),
							frappe.utils.escape_html(r.party_name || r.party),
						]),
						indicator: "orange",
					});
					return;
				}
				this._openLedger("dux-party-ledger", {
					...base,
					party: r.party,
					party_type: r.party_type,
					party_label: r.party_name,
					account: res.message,
				});
			},
		});
	}

	_ownAccounts(r, co) {
		const mc = r.member_companies || [];
		return (r.members || []).filter((m, i) => mc[i] === co);
	}

	_openOwn(base, accounts) {
		const esc = frappe.utils.escape_html;
		if (!accounts.length) {
			frappe.show_alert({
				message: __("{0} has no account under this row.", [esc(base.company)]),
				indicator: "orange",
			});
			return;
		}
		if (accounts.length === 1) {
			this._openLedger("dux-ledger", { ...base, account: accounts[0] });
			return;
		}
		// Two accounts of one company fold onto one row only when their names
		// differ in case or spacing alone. Offer both rather than guess.
		const links = accounts
			.map((a) => {
				const qs = Object.entries({ ...base, account: a })
					.filter(([, v]) => v)
					.map(([k, v]) => encodeURIComponent(k) + "=" + encodeURIComponent(v))
					.join("&");
				return `<div style="padding:4px 0"><a href="/desk/dux-ledger?${qs}" target="_blank" rel="noopener">${frappe.utils.escape_html(
					a
				)}</a></div>`;
			})
			.join("");
		frappe.msgprint({
			title: __("{0} has {1} accounts under this row", [esc(base.company), accounts.length]),
			message: links,
			indicator: "blue",
		});
	}

	/* A party opened in place under a control account, from one company's
	   column: that company's own account. */
	_drillPartyCo($tr, ci) {
		const r = (this.data.rows || [])[$tr.data("ridx")];
		const co = (this.data.companies || [])[ci];
		if (!r || !co) return;
		const acct = this._ownAccounts(r, co)[0];
		if (!acct) return;
		const f = this._ranFilters();
		const party = $tr.data("p");
		const base = { company: co, from_date: f.from_date, to_date: f.to_date, account: acct };
		if (!party) return this._openLedger("dux-ledger", base);
		this._openLedger("dux-party-ledger", {
			...base,
			party: party,
			party_type: $tr.data("pt"),
		});
	}

	/* Several companies have a figure on the row: ask which ledger to open. */
	_chooseCo(has, cv, onPick) {
		const cos = this.data.companies || [];
		const items = has
			.map((i) => {
				const f = this._coFmt(cv[i]);
				return `<div class="tb-pick-row"><a href="#" class="tb-pick" data-ci="${i}">${frappe.utils.escape_html(
					cos[i]
				)}</a><span class="${f ? f.tone : ""}">${f ? f.html : "—"}</span></div>`;
			})
			.join("");
		const dlg = frappe.msgprint({
			title: __("Open which company's ledger?"),
			message: `<div style="font-size:11.5px;color:var(--text-muted);margin-bottom:6px">${frappe.utils.escape_html(
				this._figLabel()
			)}</div>${items}`,
			indicator: "blue",
		});
		// The message dialog is shared and reused, so rebind each time.
		const $wr = (dlg && dlg.$wrapper) || $(".modal:visible");
		$wr.off("click.tbpick").on("click.tbpick", ".tb-pick", (e) => {
			e.preventDefault();
			if (dlg && dlg.hide) dlg.hide();
			onPick(Number($(e.currentTarget).data("ci")));
		});
	}

	_print() {
		const n = this._coMode() ? this._coShown().length : 0;
		if (n <= 6) return window.print();
		// Wider than a printed page. The workbook prints across pages; printing
		// the screen anyway is the other button. Closing the dialog (Esc, the
		// cross) prints nothing — a confirm read that as "No" and printed.
		const d = new frappe.ui.Dialog({
			title: __("{0} company columns", [n]),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "msg",
					options: `<p>${__(
						"With {0} company columns the table is wider than a printed page. The Excel workbook prints across pages and repeats the account column on each.",
						[n]
					)}</p>`,
				},
			],
			primary_action_label: __("Download Excel"),
			primary_action: () => {
				d.hide();
				this._excel();
			},
			secondary_action_label: __("Print anyway"),
			secondary_action: () => {
				// Once the dialog has gone, or it is printed too.
				d.$wrapper.one("hidden.bs.modal", () => window.print());
				d.hide();
			},
		});
		d.show();
	}

	_excel() {
		// The workbook is the table on screen. While a run is out there is
		// none yet, and after one failed its ask may not run at all: the
		// download would navigate this tab to the error.
		if (!this.data || this._dataSeq !== this._seq) {
			const running = this._seq && this._failedSeq !== this._seq;
			frappe.show_alert({
				message: running ? __("Wait for the run to finish.") : __("Run the report first."),
				indicator: "orange",
			});
			return;
		}
		// Same execute() the screen ran, formatted server-side, streamed
		// back as a file — not a detour through the classic report. With
		// company columns the workbook opens on the figure on screen.
		const url =
			"/api/method/dux_voucher.dux_voucher.api.reports_export.export_trial_balance_xlsx" +
			"?filters=" +
			encodeURIComponent(JSON.stringify({ ...this._ranFilters(), company_figure: this.coFig }));
		frappe.show_alert({ message: __("Building the workbook…"), indicator: "blue" });
		// Same mechanism as the other Excel buttons in this app: a
		// Content-Disposition download, so the browser saves the file
		// without navigating away and without leaving a blank tab behind.
		window.location.href = url;
	}

	_classic() {
		// Open the classic report on the selection that was run here, not on
		// its own defaults (the user's default company, the last twelve
		// months). The page's filter names are the report's own, so they
		// carry over as they are.
		const f = this.filters;
		if (f && f.company && f.company.length) {
			const ro = { ...f };
			delete ro.company_columns;
			// The classic report has no column per company; its Compare =
			// Company sets each company's signed closing side by side. Only
			// once the table on screen answers this ask: one still out may be
			// for a view that compares nothing, and the report stops on it.
			// Set either way, or a Compare left from an earlier visit stays.
			ro.compare = this._dataSeq === this._seq && this._coMode() ? "Company" : "";
			frappe.route_options = ro;
		}
		frappe.set_route("query-report", "Dux Trial Balance");
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
