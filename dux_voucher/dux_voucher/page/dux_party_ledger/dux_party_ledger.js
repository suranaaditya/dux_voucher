/* ============================================================
   dux_party_ledger.js  —  Tally-style Party Ledger
   Dux DigiTech  —  dux_voucher app

   Variant of dux_ledger.js restricted to Customer / Supplier /
   Employee parties (no account-head selection). Same data flow,
   reuses get_ledger_statement / export_ledger_xlsx unchanged; only
   the picker is constrained and the page is access-restricted.

   Wrapped in an IIFE so helpers (_pl_gel / _pl_bal / _pl_pill etc.)
   don't collide with the same-named globals declared inside
   dux_ledger.js when both pages are visited in one browser session.
   ============================================================ */

(function () {

frappe.pages["dux-party-ledger"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Party Ledger",
			single_column: true,
		});
		window._dux_party_ledger_instance = new DuxPartyLedger(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
		);
		console.error("dux-party-ledger:", e);
	}
};

frappe.pages["dux-party-ledger"].on_page_show = function (wrapper) {
	if (window._dux_party_ledger_instance && frappe.route_options) {
		window._dux_party_ledger_instance.applyRouteOptions(frappe.route_options);
		frappe.route_options = null;
	}
};

/* ============================================================
   DuxPartyLedger
   ============================================================ */
class DuxPartyLedger {
	constructor(wrapper, page) {
		this.wrapper   = wrapper;
		this.page      = page;
		this._selected = null;
		this._lastData = null;
		this._companies = [];   // populated by _loadCompanies
		this._showAllDetails = false;       // global "Show details" toggle
		this._expandedRows = new Set();     // per-row drill-down state

		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();
	}

	_injectStyles() {
		if (document.getElementById("pl-styles")) return;
		var s = document.createElement("style");
		s.id = "pl-styles";
		s.textContent = `
.pl-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.pl-filter-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px 24px;margin-bottom:20px;display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px}
.pl-fg{display:flex;flex-direction:column;gap:5px}
.pl-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.pl-fg select,.pl-fg input[type=text],.pl-fg input[type=date]{height:36px;border:1px solid #e5e7eb;border-radius:7px;padding:0 11px;font-size:13px;color:#111827;background:#fff;outline:none;transition:border .15s;font-family:inherit;box-sizing:border-box}
.pl-fg select:focus,.pl-fg input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.08)}
#pl-co-inp{min-width:220px}
#pl-acc-inp{min-width:280px}
#pl-from,#pl-to{width:148px}
.pl-fg-co{position:relative}
/* top:100% pins the dropdown to the bottom of its .pl-fg-* container.
   The previous top:auto relied on the browser's "static position"
   computation for absolute-inside-flex-column, which Chrome resolves
   to 0 — the dropdown rendered on top of the label instead of below
   the input. */
.pl-drop{position:absolute;z-index:9999;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.12);min-width:340px;max-height:300px;overflow-y:auto;margin-top:3px;top:100%;left:0}
/* Company picker dropdown — narrower so it doesn't bleed into the Party column to its right. */
#pl-co-drop{min-width:240px}
.pl-drop-section{padding:6px 12px 3px;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid #f3f4f6;background:#fafafa}
.pl-drop-item{padding:9px 14px;cursor:pointer;display:flex;flex-direction:column;gap:2px;border-bottom:1px solid #f9fafb}
.pl-drop-item:last-child{border-bottom:none}
.pl-drop-item:hover{background:#f0f4ff}
.pl-drop-label{font-size:13px;font-weight:500;color:#111827}
.pl-drop-meta{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace}
.pl-drop-empty{padding:16px;font-size:13px;color:#9ca3af;text-align:center}
.pl-fg-acc{position:relative}
.pl-sel-pill{display:inline-flex;align-items:center;gap:5px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:5px;padding:2px 8px;font-size:12px;font-weight:500;color:#1d4ed8;margin-bottom:4px;cursor:pointer}
.pl-sel-pill-x{font-size:14px;line-height:1;color:#93c5fd;margin-left:2px}
.pl-sel-pill-x:hover{color:#1d4ed8}
.pl-btn-row{display:flex;gap:8px;align-items:flex-end}
.pl-btn{height:36px;padding:0 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;font-family:inherit;transition:all .15s}
.pl-btn-primary{background:#2563eb;border-color:#2563eb;color:#fff}
.pl-btn-primary:hover{background:#1d4ed8}
.pl-btn-secondary{background:#fff;color:#374151}
.pl-btn-secondary:hover{background:#f9fafb}
.pl-print-split{display:none;position:relative}
.pl-print-split-inner{display:flex;border:1px solid #e5e7eb;border-radius:7px;overflow:hidden}
.pl-print-main{height:36px;padding:0 14px;font-size:13px;font-weight:600;cursor:pointer;border:none;border-right:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:background .15s;display:flex;align-items:center;gap:6px}
.pl-print-main:hover{background:#f9fafb}
.pl-print-caret{height:36px;width:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;background:#fff;color:#9ca3af;font-family:inherit;transition:background .15s}
.pl-print-caret:hover{background:#f3f4f6;color:#374151}
.pl-print-menu{position:absolute;right:0;top:40px;background:#fff;border:1px solid #e5e7eb;border-radius:7px;box-shadow:0 8px 24px rgba(0,0,0,.1);min-width:170px;z-index:100;display:none}
.pl-print-menu.open{display:block}
.pl-print-opt{padding:10px 14px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:9px;color:#374151;border-bottom:1px solid #f3f4f6}
.pl-print-opt:last-child{border-bottom:none}
.pl-print-opt:hover{background:#f0f4ff;color:#1d4ed8}
.pl-excel-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #16a34a;background:#16a34a;color:#fff;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.pl-excel-btn:hover{background:#15803d;border-color:#15803d}
.pl-placeholder{text-align:center;padding:64px 20px;color:#9ca3af;font-size:14px}
.pl-placeholder strong{color:#6b7280}
.pl-report-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
.pl-rpt-hdr{padding:18px 24px 14px;border-bottom:1px solid #f3f4f6}
.pl-rpt-co{font-size:16px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.01em}
.pl-rpt-ledger-row{display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;margin-bottom:4px}
.pl-rpt-ledger-row strong{font-weight:600}
.pl-acc-type-badge{font-size:10px;font-weight:700;background:#eff6ff;color:#2563eb;border-radius:4px;padding:2px 7px;letter-spacing:.03em}
.pl-party-badge{font-size:10px;font-weight:700;background:#f0fdf4;color:#166534;border-radius:4px;padding:2px 7px;letter-spacing:.03em}
.pl-rpt-period{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace;display:flex;align-items:center;gap:8px}
.pl-rpt-period span{background:#f9fafb;border:1px solid #f3f4f6;border-radius:4px;padding:1px 7px}
.pl-tbl-wrap{overflow-x:auto}
.pl-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.pl-tbl thead th{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;padding:9px 16px;background:#fafafa;border-bottom:1px solid #f3f4f6;white-space:nowrap;font-family:inherit}
.pl-tbl thead th.r{text-align:right}
.pl-tr-ob td,.pl-tr-cb td{padding:10px 16px;background:#f9fafb;font-size:12px}
.pl-tr-ob td{border-bottom:1px solid #f3f4f6}
.pl-tr-cb td{border-top:2px solid #e5e7eb}
.pl-ob-label,.pl-cb-label{font-weight:700;color:#374151;text-transform:uppercase;font-size:10px;letter-spacing:.08em}
.pl-tr-e td{padding:10px 16px;border-bottom:1px solid #f9fafb;vertical-align:top}
.pl-tr-e:hover td{background:#fafbff}
.pl-tr-r td{padding:1px 16px 9px 32px;border-bottom:1px solid #f9fafb;font-size:11px;color:#9ca3af;font-style:italic;line-height:1.5}
.pl-tr-tot td{padding:10px 16px;border-top:2px solid #e5e7eb;font-size:12.5px;font-weight:700}
.pl-tot-label{text-align:right;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;font-weight:700}
.pl-c-date{width:80px;color:#9ca3af;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px}
.pl-c-part{min-width:180px}
.pl-c-vt{width:130px;white-space:nowrap}
.pl-c-vno{width:130px;white-space:nowrap}
.pl-c-amt{width:110px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.pl-c-bal{width:120px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.pl-to{color:#2563eb;font-weight:700;font-size:11px;margin-right:4px}
.pl-by{color:#059669;font-weight:700;font-size:11px;margin-right:4px}
.pl-contra-name{color:#111827;font-weight:500;font-size:13px}
.pl-vno{color:#2563eb;text-decoration:none;font-size:12px;font-family:'SFMono-Regular',Consolas,monospace}
.pl-vno:hover{text-decoration:underline}
.pl-dr{color:#dc2626;font-weight:500}
.pl-cr{color:#059669;font-weight:500}
.pl-nil{color:#d1d5db}
.pl-bal-dr{color:#dc2626;font-weight:700}
.pl-bal-cr{color:#059669;font-weight:700}
.pl-bsuf{font-size:9px;margin-left:2px;font-weight:700;opacity:.65;letter-spacing:.04em}
.pl-pill{display:inline-block;font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;letter-spacing:.03em;white-space:nowrap;font-family:inherit}
.pl-pill-pv{background:#eff6ff;color:#1d4ed8}
.pl-pill-rv{background:#f0fdf4;color:#166534}
.pl-pill-jv{background:#fffbeb;color:#92400e}
.pl-pill-cv{background:#f5f3ff;color:#5b21b6}
.pl-pill-pi{background:#fff7ed;color:#c2410c}
.pl-pill-si{background:#f0fdf4;color:#166534}
.pl-pill-other{background:#f3f4f6;color:#4b5563;border:1px solid #e5e7eb}
.pl-detail-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.pl-detail-btn:hover{background:#f9fafb}
.pl-detail-btn.active{background:#eff6ff;border-color:#bfdbfe;color:#1d4ed8}
.pl-chev{display:inline-block;width:13px;color:#9ca3af;font-size:10px;margin-right:3px;user-select:none}
.pl-expandable{cursor:pointer}
.pl-expandable:hover .pl-chev{color:#2563eb}
.pl-bd-count{color:#9ca3af;font-size:11px;margin-left:5px}
.pl-tr-bd td{padding:5px 16px;border-bottom:1px solid #f9fafb;background:#fcfcfd;font-size:11.5px;vertical-align:top}
.pl-bd-part{color:#475569;padding-left:42px!important}
.pl-bd-arrow{color:#9ca3af;margin-right:5px}
.pl-c-part,.pl-contra-name{word-break:break-word}
@media(max-width:900px){
  .pl-tbl{font-size:11.5px}
  .pl-tbl thead th{padding:8px 9px}
  .pl-tr-e td,.pl-tr-ob td,.pl-tr-cb td,.pl-tr-tot td,.pl-tr-bd td{padding:8px 9px}
  .pl-c-date{width:58px;font-size:11px}
  .pl-c-vt{width:96px}
  .pl-c-vno{width:96px}
  .pl-c-amt{width:84px}
  .pl-c-bal{width:92px}
  .pl-c-part{min-width:110px}
  .pl-tr-r td{padding-left:16px}
  .pl-bd-part{padding-left:28px!important}
}
@media(max-width:600px){
  .pl-tbl{font-size:11px}
  .pl-tbl thead th,.pl-tr-e td,.pl-tr-ob td,.pl-tr-cb td,.pl-tr-tot td,.pl-tr-bd td{padding:6px 6px}
  .pl-c-vt{width:76px}
  .pl-c-vno{width:84px}
  .pl-c-amt{width:76px}
  .pl-c-bal{width:84px}
  .pl-c-part{min-width:80px}
  .pl-pill{font-size:9px;padding:2px 5px}
}
		`;
		document.head.appendChild(s);
	}

	_renderLayout() {
		$(this.wrapper).find(".layout-main-section").html(`
<div class="pl-wrap">
  <div class="pl-filter-card">
    <div class="pl-fg pl-fg-co">
      <label>Company</label>
      <div id="pl-co-pill-wrap"></div>
      <input id="pl-co-inp" type="text" placeholder="Type to search company…" autocomplete="off">
      <input id="pl-co-sel" type="hidden">
      <div class="pl-drop" id="pl-co-drop" style="display:none"></div>
    </div>
    <div class="pl-fg pl-fg-acc">
      <label>Party</label>
      <div id="pl-sel-pill-wrap"></div>
      <input id="pl-acc-inp" type="text" placeholder="Type to search suppliers, customers, employees…" autocomplete="off">
      <div class="pl-drop" id="pl-drop" style="display:none"></div>
    </div>
    <div class="pl-fg"><label>From</label><input id="pl-from" type="date"></div>
    <div class="pl-fg"><label>To</label><input id="pl-to" type="date"></div>
    <div class="pl-btn-row">
      <button class="pl-btn pl-btn-primary" id="pl-show-btn">Show</button>
      <button class="pl-excel-btn" id="pl-excel-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M8 13l3 3-3 3M14 13l-3 3 3 3"/></svg>Excel
      </button>
      <button class="pl-detail-btn" id="pl-detail-btn" title="Expand every 'Various' row into its individual heads">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg><span class="pl-detail-lbl">Show details</span>
      </button>
      <div class="pl-print-split" id="pl-print-split">
        <div class="pl-print-split-inner">
          <button class="pl-print-main" id="pl-print-p-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Print
          </button>
          <button class="pl-print-caret" id="pl-print-caret">
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div class="pl-print-menu" id="pl-print-menu">
          <div class="pl-print-opt" id="pl-opt-p">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Portrait (A4)
          </div>
          <div class="pl-print-opt" id="pl-opt-l">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>Landscape (A4)
          </div>
        </div>
      </div>
    </div>
  </div>
  <div id="pl-area">
    <div class="pl-placeholder">Select a company and a party, then click <strong>Show</strong>.</div>
  </div>
</div>`);
	}

	_bindEvents() {
		var self = this;
		// Company picker — type-to-filter; click-to-select stays in
		// _renderCompanyDropdown.
		_gel("pl-co-inp").addEventListener("input", function(){
			self._renderCompanyDropdown(this.value);
		});
		_gel("pl-co-inp").addEventListener("focus", function(){
			self._renderCompanyDropdown(this.value);
		});
		// Account / party picker (unchanged).
		_gel("pl-acc-inp").addEventListener("input", _debounce(function(){
			var co=_gel("pl-co-sel").value, txt=this.value.trim();
			if(co&&txt.length>=2) self._search(co,txt);
			else _gel("pl-drop").style.display="none";
		},280));
		_gel("pl-acc-inp").addEventListener("focus", function(){
			var co=_gel("pl-co-sel").value, txt=this.value.trim();
			if(co&&txt.length>=2) self._search(co,txt);
		});
		document.addEventListener("click", function(e){
			if(!e.target.closest(".pl-fg-co"))  _gel("pl-co-drop").style.display="none";
			if(!e.target.closest(".pl-fg-acc")) _gel("pl-drop").style.display="none";
			if(!e.target.closest(".pl-print-split")) _gel("pl-print-menu").classList.remove("open");
		});
		_gel("pl-show-btn").addEventListener("click", function(){ self.fetchReport(); });
		_gel("pl-excel-btn").addEventListener("click", function(){ self._exportExcel(); });
		_gel("pl-detail-btn").addEventListener("click", function(){ self._toggleAllDetails(); });
		_gel("pl-print-p-btn").addEventListener("click", function(){ _gel("pl-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("pl-print-caret").addEventListener("click", function(e){ e.stopPropagation(); _gel("pl-print-menu").classList.toggle("open"); });
		_gel("pl-opt-p").addEventListener("click",  function(){ _gel("pl-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("pl-opt-l").addEventListener("click",  function(){ _gel("pl-print-menu").classList.remove("open"); self._printReport(true); });
		["pl-co-inp","pl-acc-inp","pl-from","pl-to"].forEach(function(id){
			_gel(id).addEventListener("keydown", function(ev){ if(ev.key==="Enter") self.fetchReport(); });
		});
	}

	_setDefaultDates() {
		var now=new Date(), m=now.getMonth(), yr=now.getFullYear();
		var fy=m>=3?yr:yr-1;
		_gel("pl-from").value=fy+"-04-01";
		_gel("pl-to").value=now.toISOString().split("T")[0];
	}

	_loadCompanies() {
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_permitted_companies",
			callback:function(r){
				self._companies = r.message || [];
				// If only one company is permitted, auto-select so the
				// counter operator doesn't have to click through a
				// single-item picker.
				if(self._companies.length === 1) self._selectCompany(self._companies[0]);
			},
		});
	}

	_renderCompanyDropdown(filterTxt){
		var self=this, drop=_gel("pl-co-drop");
		var lc=(filterTxt||"").toLowerCase();
		var matched=this._companies.filter(function(c){ return c.toLowerCase().indexOf(lc)!==-1; });
		if(!matched.length){
			drop.innerHTML='<div class="pl-drop-empty">No companies match</div>';
			drop.style.display="block";
			return;
		}
		drop.innerHTML=matched.map(function(c){
			return `<div class="pl-drop-item pl-co-item" data-v="${_esc(c)}"><span class="pl-drop-label">${_esc(c)}</span></div>`;
		}).join("");
		drop.style.display="block";
		drop.querySelectorAll(".pl-co-item").forEach(function(el){
			el.addEventListener("click", function(){ self._selectCompany(el.dataset.v); });
		});
	}

	_selectCompany(name){
		var self=this;
		_gel("pl-co-sel").value=name;
		_gel("pl-co-inp").value="";
		_gel("pl-co-inp").placeholder="Selected ↑ — type to change";
		_gel("pl-co-drop").style.display="none";
		_gel("pl-co-pill-wrap").innerHTML=
			`<div class="pl-sel-pill">${_esc(name)}<span class="pl-sel-pill-x" id="pl-co-clear">×</span></div>`;
		_gel("pl-co-clear").addEventListener("click", function(){ self._clearCompany(); });
		// Account / party choice is company-scoped — wipe it so the
		// user re-picks one valid in the new company.
		this._clearSelection();
	}

	_clearCompany(){
		_gel("pl-co-sel").value="";
		_gel("pl-co-inp").value="";
		_gel("pl-co-inp").placeholder="Type to search company…";
		_gel("pl-co-pill-wrap").innerHTML="";
		_gel("pl-co-drop").style.display="none";
		this._clearSelection();
	}

	_clearSelection(){
		this._selected=null;
		_gel("pl-acc-inp").value="";
		_gel("pl-acc-inp").placeholder="Type to search suppliers, customers, employees…";
		_gel("pl-sel-pill-wrap").innerHTML="";
		_gel("pl-drop").style.display="none";
	}

	_selectItem(item){
		var self=this;
		this._selected=item;
		_gel("pl-acc-inp").value="";
		_gel("pl-acc-inp").placeholder="Selected ↑ — type to change";
		_gel("pl-drop").style.display="none";
		_gel("pl-sel-pill-wrap").innerHTML=
			`<div class="pl-sel-pill">${_esc(item.label)}<span class="pl-sel-pill-x" id="pl-clear-sel">×</span></div>`;
		document.getElementById("pl-clear-sel").addEventListener("click",function(){ self._clearSelection(); });
	}

	_search(company, txt){
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.search_ledger",
			// parties_only=1 → backend skips the Account branch, so the
			// dropdown only ever shows Customers / Suppliers / Employees.
			args:{company:company,search_txt:txt,parties_only:1},
			callback:function(r){
				var results=r.message||[], drop=_gel("pl-drop");
				if(!results.length){ drop.innerHTML='<div class="pl-drop-empty">No parties match</div>'; drop.style.display="block"; return; }
				// Skip the Accounts section entirely — purchase-team view
				// is parties-only by design.
				var par=results.filter(function(x){return x.type==="party";});
				var html='<div class="pl-drop-section">Parties</div>'+par.map(function(i){
					return `<div class="pl-drop-item" data-v='${JSON.stringify(i).replace(/'/g,"&#39;")}'><span class="pl-drop-label">${_esc(i.label)}</span><span class="pl-drop-meta">${_esc(i.meta)}</span></div>`;
				}).join("");
				drop.innerHTML=html; drop.style.display="block";
				drop.querySelectorAll(".pl-drop-item").forEach(function(el){
					el.addEventListener("click",function(){ var item=JSON.parse(el.dataset.v); self._selectItem(item); self.fetchReport(); });
				});
			},
		});
	}

	applyRouteOptions(opts){
		if(opts.company)   this._selectCompany(opts.company);
		if(opts.account)   _gel("pl-acc-inp").value=opts.account;
		if(opts.from_date) _gel("pl-from").value=opts.from_date;
		if(opts.to_date)   _gel("pl-to").value=opts.to_date;
		if(opts.company&&opts.account) this.fetchReport();
	}

	fetchReport(){
		var company=_gel("pl-co-sel").value,
		    from_date=_gel("pl-from").value,
		    to_date=_gel("pl-to").value;
		var account="",party=null,party_type=null;
		if(this._selected){
			if(this._selected.type==="account"){ account=this._selected.value; }
			else{ account=this._selected.account; party=this._selected.value; party_type=this._selected.party_type; }
		} else { account=_gel("pl-acc-inp").value.trim(); }
		if(!company){ frappe.msgprint({message:"Please select a Company.",indicator:"orange"}); return; }
		if(!account){ frappe.msgprint({message:"Please select a Party.",indicator:"orange"}); return; }
		if(!from_date||!to_date){ frappe.msgprint({message:"Please set both dates.",indicator:"orange"}); return; }
		_gel("pl-area").innerHTML='<div class="pl-placeholder">Loading…</div>';
		_gel("pl-print-split").style.display="none";
		_gel("pl-excel-btn").style.display="none";
		this._lastData=null;
		var self=this, args={company,account,from_date,to_date};
		if(party)      args.party=party;
		if(party_type) args.party_type=party_type;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_ledger_statement",
			args:args,
			callback:function(r){
				if(r.message){ self._lastData=r.message; self._render(r.message); _gel("pl-print-split").style.display="block"; _gel("pl-excel-btn").style.display="inline-flex"; }
				else{ _gel("pl-area").innerHTML='<div class="pl-placeholder">No data found for this selection and period.</div>'; }
			},
			error:function(){ _gel("pl-area").innerHTML='<div class="pl-placeholder" style="color:#dc2626">Could not load report. Verify the party and try again.</div>'; },
		});
	}

	_render(d){
		var self=this;
		// Fresh data — start collapsed.
		this._showAllDetails=false;
		this._expandedRows=new Set();
		var rows="";
		rows+=`<tr class="pl-tr-ob"><td colspan="4"><span class="pl-ob-label">Opening Balance</span></td><td class="pl-c-amt">${d.opening_debit>0?`<span class="pl-dr">${_fmt(d.opening_debit)}</span>`:'<span class="pl-nil">—</span>'}</td><td class="pl-c-amt">${d.opening_credit>0?`<span class="pl-cr">${_fmt(d.opening_credit)}</span>`:'<span class="pl-nil">—</span>'}</td><td class="pl-c-bal">${_bal(d.opening_balance,d.opening_type)}</td></tr>`;
		if(!d.rows.length) rows+=`<tr><td colspan="7" class="pl-placeholder" style="padding:32px">No transactions in this period.</td></tr>`;
		d.rows.forEach(function(row,i){
			var pCls=row.prefix==="To"?"pl-to":"pl-by";
			var drHtml=row.debit>0?`<span class="pl-dr">${_fmt(row.debit)}</span>`:`<span class="pl-nil">—</span>`;
			var crHtml=row.credit>0?`<span class="pl-cr">${_fmt(row.credit)}</span>`:`<span class="pl-nil">—</span>`;
			var hasBd=row.breakdown&&row.breakdown.length;
			var chev=hasBd?`<span class="pl-chev">▸</span>`:"";
			var cnt=hasBd?`<span class="pl-bd-count">(${row.breakdown.length})</span>`:"";
			rows+=`<tr class="pl-tr-e${hasBd?" pl-expandable":""}" data-r="${i}"><td class="pl-c-date">${_esc(row.posting_date)}</td><td class="pl-c-part">${chev}<span class="${pCls}">${row.prefix}</span><span class="pl-contra-name">${_esc(row.contra)}</span>${cnt}</td><td class="pl-c-vt">${_pill(row.voucher_type)}</td><td class="pl-c-vno"><a class="pl-vno" href="${_esc(row.voucher_url)}" target="_blank">${_esc(row.voucher_no)}</a></td><td class="pl-c-amt">${drHtml}</td><td class="pl-c-amt">${crHtml}</td><td class="pl-c-bal">${_bal(row.balance,row.balance_type)}</td></tr>`;
			if(hasBd){
				row.breakdown.forEach(function(b){
					var amtCells=b.side==="Cr"
						?`<td class="pl-c-amt"></td><td class="pl-c-amt"><span class="pl-cr">${_fmt(b.amount)}</span></td>`
						:`<td class="pl-c-amt"><span class="pl-dr">${_fmt(b.amount)}</span></td><td class="pl-c-amt"></td>`;
					rows+=`<tr class="pl-tr-bd" data-bd="${i}" style="display:none"><td class="pl-c-date"></td><td class="pl-c-part pl-bd-part"><span class="pl-bd-arrow">↳</span>${_esc(b.label)}</td><td class="pl-c-vt"></td><td class="pl-c-vno"></td>${amtCells}<td class="pl-c-bal"></td></tr>`;
				});
			}
			if(row.remarks) rows+=`<tr class="pl-tr-r"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
		});
		rows+=`<tr class="pl-tr-cb"><td colspan="4"><span class="pl-cb-label">Closing Balance</span></td><td class="pl-c-amt">${d.closing_balancing_debit>0?`<span class="pl-dr">${_fmt(d.closing_balancing_debit)}</span>`:'<span class="pl-nil">—</span>'}</td><td class="pl-c-amt">${d.closing_balancing_credit>0?`<span class="pl-cr">${_fmt(d.closing_balancing_credit)}</span>`:'<span class="pl-nil">—</span>'}</td><td class="pl-c-bal" style="font-size:13px">${_bal(d.closing_balance,d.closing_type)}</td></tr>`;
		rows+=`<tr class="pl-tr-tot"><td colspan="4" class="pl-tot-label">Total</td><td class="pl-c-amt"><span class="pl-dr">${_fmt(d.grand_total_debit)}</span></td><td class="pl-c-amt"><span class="pl-cr">${_fmt(d.grand_total_credit)}</span></td><td class="pl-c-bal"></td></tr>`;
		var isParty=["Customer","Supplier","Employee"].includes(d.account_type);
		var badge=d.account_type?`<span class="${isParty?"pl-party-badge":"pl-acc-type-badge"}">${_esc(d.account_type)}</span>`:"";
		_gel("pl-area").innerHTML=`
<div class="pl-report-card">
  <div class="pl-rpt-hdr">
    <div class="pl-rpt-co">${_esc(d.company)}</div>
    <div class="pl-rpt-ledger-row"><span>Ledger:</span><strong>${_esc(d.account_name)}</strong>${badge}</div>
    <div class="pl-rpt-period"><span>${_esc(d.from_date)}</span><span style="color:#d1d5db">→</span><span>${_esc(d.to_date)}</span><span style="color:#d1d5db">·</span><span>${d.row_count} transaction${d.row_count!==1?"s":""}</span></div>
  </div>
  <div class="pl-tbl-wrap">
    <table class="pl-tbl">
      <thead><tr>
        <th class="pl-c-date">Date</th><th class="pl-c-part">Particulars</th>
        <th class="pl-c-vt">Vch Type</th><th class="pl-c-vno">Vch No</th>
        <th class="pl-c-amt r">Debit</th><th class="pl-c-amt r">Credit</th>
        <th class="pl-c-bal r">Balance</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
		// Show the "Show details" toggle only when something is expandable.
		var anyBd=d.rows.some(function(r){ return r.breakdown&&r.breakdown.length; });
		var dbtn=_gel("pl-detail-btn");
		if(dbtn){
			dbtn.style.display=anyBd?"inline-flex":"none";
			dbtn.classList.remove("active");
			var lbl=dbtn.querySelector(".pl-detail-lbl"); if(lbl) lbl.textContent="Show details";
		}
		this._attachDetailHandlers();
	}

	/* ── "Various" drill-down: per-row click + global toggle ─────── */
	_attachDetailHandlers(){
		var self=this, area=_gel("pl-area");
		if(!area) return;
		area.querySelectorAll(".pl-expandable").forEach(function(tr){
			tr.addEventListener("click", function(ev){
				if(ev.target.closest("a")) return;   // let the Vch No link work
				self._toggleRow(parseInt(tr.dataset.r,10));
			});
		});
	}

	_toggleRow(i){
		if(this._expandedRows.has(i)) this._expandedRows.delete(i);
		else this._expandedRows.add(i);
		this._applyRowVisibility(i);
	}

	_applyRowVisibility(i){
		var expanded=this._showAllDetails||this._expandedRows.has(i);
		var area=_gel("pl-area");
		area.querySelectorAll('.pl-tr-bd[data-bd="'+i+'"]').forEach(function(tr){
			tr.style.display=expanded?"":"none";
		});
		var chev=area.querySelector('.pl-expandable[data-r="'+i+'"] .pl-chev');
		if(chev) chev.textContent=expanded?"▾":"▸";
	}

	_toggleAllDetails(){
		this._showAllDetails=!this._showAllDetails;
		var self=this, area=_gel("pl-area");
		if(area) area.querySelectorAll(".pl-expandable").forEach(function(tr){
			self._applyRowVisibility(parseInt(tr.dataset.r,10));
		});
		var dbtn=_gel("pl-detail-btn");
		if(dbtn){
			dbtn.classList.toggle("active", this._showAllDetails);
			var lbl=dbtn.querySelector(".pl-detail-lbl");
			if(lbl) lbl.textContent=this._showAllDetails?"Hide details":"Show details";
		}
	}

	/* ══════════════════════════════════════════════════════════
	   Excel export — streams styled .xlsx via openpyxl backend
	   ══════════════════════════════════════════════════════════ */
	_exportExcel(){
		if(!this._lastData) return;
		var company=_gel("pl-co-sel").value,
		    from_date=_gel("pl-from").value,
		    to_date=_gel("pl-to").value;
		var account="",party=null,party_type=null;
		if(this._selected){
			if(this._selected.type==="account"){ account=this._selected.value; }
			else{ account=this._selected.account; party=this._selected.value; party_type=this._selected.party_type; }
		} else { account=_gel("pl-acc-inp").value.trim(); }
		var params=new URLSearchParams({company:company,account:account,from_date:from_date,to_date:to_date});
		if(party)      params.append("party",party);
		if(party_type) params.append("party_type",party_type);
		var url="/api/method/dux_voucher.dux_voucher.api.reports_export.export_ledger_xlsx?"+params.toString();
		window.location.href=url;
	}

	/* ══════════════════════════════════════════════════════════
	   Professional Print — opens in clean new window
	   ══════════════════════════════════════════════════════════ */
	_printReport(landscape){
		if(!this._lastData) return;
		var self=this, d=this._lastData;
		var win=window.open("","_blank","width=1100,height=750");
		if(!win){ frappe.msgprint("Please allow pop-ups for this site."); return; }

		var pageRule=landscape
			? "@page{size:A4 landscape;margin:12mm 14mm 14mm}"
			: "@page{size:A4 portrait;margin:16mm 12mm 14mm}";

		var isParty=["Customer","Supplier","Employee"].includes(d.account_type);
		var printedDate=new Date().toLocaleDateString("en-IN",{day:"2-digit",month:"long",year:"numeric"});

		/* Build table rows */
		var tRows="";

		// Opening balance
		tRows+=`<tr class="p-ob">
			<td colspan="4" class="p-ob-lbl">Opening Balance</td>
			<td class="p-num">${d.opening_debit>0?`<span class="p-dr">${_fmt(d.opening_debit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num">${d.opening_credit>0?`<span class="p-cr">${_fmt(d.opening_credit)}</span>`:'<span class="p-nil">—</span>'}</td>
			<td class="p-num p-fw ${d.opening_type==="Dr"?"p-dr":"p-cr"}">${_fmt(d.opening_balance)}<span class="p-suf">${d.opening_type}</span></td>
		</tr>`;

		d.rows.forEach(function(row,idx){
			var kwHtml=row.prefix==="To"?'<span class="p-to">To</span>':'<span class="p-by">By</span>';
			var drHtml=row.debit>0?`<span class="p-dr">${_fmt(row.debit)}</span>`:'<span class="p-nil">—</span>';
			var crHtml=row.credit>0?`<span class="p-cr">${_fmt(row.credit)}</span>`:'<span class="p-nil">—</span>';
			var balCls=row.balance_type==="Dr"?"p-dr":"p-cr";
			tRows+=`<tr class="p-erow ${idx%2===0?"p-even":"p-odd"}">
				<td class="p-dt">${_esc(row.posting_date)}</td>
				<td class="p-part">${kwHtml} ${_esc(row.contra)}</td>
				<td class="p-vt">${_esc(row.voucher_type)}</td>
				<td class="p-vno">${_esc(row.voucher_no)}</td>
				<td class="p-num">${drHtml}</td>
				<td class="p-num">${crHtml}</td>
				<td class="p-num p-fw ${balCls}">${_fmt(row.balance)}<span class="p-suf">${row.balance_type}</span></td>
			</tr>`;
			if(self._showAllDetails||self._expandedRows.has(idx)){
				(row.breakdown||[]).forEach(function(b){
					var bd=b.side==="Cr"
						?`<td class="p-num"></td><td class="p-num"><span class="p-cr">${_fmt(b.amount)}</span></td>`
						:`<td class="p-num"><span class="p-dr">${_fmt(b.amount)}</span></td><td class="p-num"></td>`;
					tRows+=`<tr class="p-erow ${idx%2===0?"p-even":"p-odd"}"><td></td><td class="p-part" style="padding-left:18px;color:#475569;font-size:9.5px">↳ ${_esc(b.label)}</td><td></td><td></td>${bd}<td class="p-num"></td></tr>`;
				});
			}
			if(row.remarks) tRows+=`<tr class="p-rmk"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
		});

		// Closing balance
		tRows+=`<tr class="p-cb">
			<td colspan="4" class="p-ob-lbl">Closing Balance</td>
			<td class="p-num">${d.closing_balancing_debit>0?`<span class="p-dr">${_fmt(d.closing_balancing_debit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num">${d.closing_balancing_credit>0?`<span class="p-cr">${_fmt(d.closing_balancing_credit)}</span>`:'<span class="p-nil">—</span>'}</td>
			<td class="p-num p-fw" style="font-size:12.5px;${d.closing_type==="Dr"?"color:#dc2626":"color:#16a34a"}">${_fmt(d.closing_balance)}<span class="p-suf">${d.closing_type}</span></td>
		</tr>`;

		// Totals
		tRows+=`<tr class="p-tot">
			<td colspan="4" class="p-tot-lbl">Total</td>
			<td class="p-num p-dr">${_fmt(d.grand_total_debit)}</td>
			<td class="p-num p-cr">${_fmt(d.grand_total_credit)}</td>
			<td class="p-num"></td>
		</tr>`;

		var badgeHtml=d.account_type
			?`<span class="${isParty?"p-badge-party":"p-badge"}">${_esc(d.account_type)}</span>`
			:"";

		win.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Party Ledger — ${_esc(d.account_name)}</title>
<style>
${pageRule}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#fff;color:#1e293b}
body{font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:11px;line-height:1.45;padding:0}
.p-wrap{display:flex;flex-direction:column;min-height:100vh}

/* ── Header ── */
.p-hdr{display:flex;justify-content:space-between;align-items:flex-end;padding-bottom:10px;margin-bottom:14px;border-bottom:3px solid #0f172a}
.p-hdr-left{}
.p-rtype{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.18em;color:#94a3b8;margin-bottom:5px}
.p-coname{font-size:21px;font-weight:800;color:#0f172a;letter-spacing:-.4px;line-height:1.1}
.p-hdr-right{text-align:right;font-size:9px;color:#94a3b8;padding-bottom:2px}

/* ── Info bar ── */
.p-info{display:flex;justify-content:space-between;align-items:center;background:#f8fafc;border:1px solid #e2e8f0;border-left:4.5px solid #2563eb;border-radius:0 6px 6px 0;padding:10px 16px;margin-bottom:16px}
.p-info-lbl{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#94a3b8;margin-bottom:4px}
.p-info-name{font-size:14px;font-weight:800;color:#0f172a;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.p-badge{display:inline-block;font-size:8.5px;font-weight:700;background:#eff6ff;color:#1d4ed8;border-radius:3px;padding:2px 7px;letter-spacing:.05em}
.p-badge-party{background:#f0fdf4;color:#166534}
.p-info-right{text-align:right}
.p-period{font-size:10px;color:#475569;font-family:'Courier New',monospace;margin-bottom:2px}
.p-txncount{font-size:9px;color:#94a3b8}

/* ── Table ── */
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
table{width:100%;border-collapse:collapse}
thead tr{background:#1e293b}
thead th{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#f1f5f9;padding:7px 9px;white-space:nowrap}
thead th.r{text-align:right}

.p-ob td{background:#dbeafe;padding:8px 9px;border-top:1px solid #93c5fd;border-bottom:1px solid #93c5fd}
.p-cb td{background:#dbeafe;padding:8px 9px;border-top:2.5px solid #0f172a;border-bottom:1px solid #93c5fd}
.p-ob-lbl{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;color:#1e3a5f}

.p-even td{background:#fff;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-odd  td{background:#fafbfc;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-rmk td{padding:0 9px 6px 22px;border-bottom:1px solid #f1f5f9;font-size:9px;color:#94a3b8;font-style:italic;line-height:1.5}

.p-tot td{border-top:2.5px solid #0f172a;padding:8px 9px;font-weight:800;background:#f8fafc}
.p-tot-lbl{text-align:right;font-size:8.5px;text-transform:uppercase;letter-spacing:.1em;color:#64748b}

.p-dt{width:66px;color:#64748b;font-family:'Courier New',monospace;font-size:10px;white-space:nowrap}
.p-part{font-size:11px;color:#0f172a}
.p-vt{width:108px;font-size:10px;color:#374151;white-space:nowrap}
.p-vno{width:118px;font-family:'Courier New',monospace;font-size:10px;color:#1d4ed8;white-space:nowrap}
.p-num{width:94px;text-align:right;font-family:'Courier New',monospace;font-size:11px;white-space:nowrap}
.p-fw{font-weight:700}

.p-to{color:#1d4ed8;font-weight:800;font-size:9.5px;margin-right:3px}
.p-by{color:#16a34a;font-weight:800;font-size:9.5px;margin-right:3px}
.p-dr{color:#dc2626}
.p-cr{color:#16a34a}
.p-nil{color:#cbd5e1}
.p-suf{font-size:8px;margin-left:1px;font-weight:800;opacity:.7}

/* ── Footer ── */
.p-foot{margin-top:20px;padding-top:10px;border-top:1px solid #e2e8f0;text-align:right;font-size:9px;color:#94a3b8}

@media print{
  thead{display:table-header-group}
  .p-erow,.p-rmk{page-break-inside:avoid}
  .p-ob,.p-cb,.p-tot{page-break-inside:avoid}
}
</style>
</head>
<body>
<div class="p-wrap">

<div class="p-hdr">
  <div class="p-hdr-left">
    <div class="p-rtype">Party Ledger</div>
    <div class="p-coname">${_esc(d.company)}</div>
  </div>
  <div class="p-hdr-right">Printed: ${_esc(printedDate)}</div>
</div>

<div class="p-info">
  <div>
    <div class="p-info-lbl">Account / Ledger</div>
    <div class="p-info-name">${_esc(d.account_name)} ${badgeHtml}</div>
  </div>
  <div class="p-info-right">
    <div class="p-period">${_esc(d.from_date)}  →  ${_esc(d.to_date)}</div>
    <div class="p-txncount">${d.row_count} transaction${d.row_count!==1?"s":""}</div>
  </div>
</div>

<table>
  <thead>
    <tr>
      <th class="p-dt">Date</th>
      <th class="p-part">Particulars</th>
      <th class="p-vt">Vch Type</th>
      <th class="p-vno">Vch No</th>
      <th class="p-num r">Debit (₹)</th>
      <th class="p-num r">Credit (₹)</th>
      <th class="p-num r">Balance (₹)</th>
    </tr>
  </thead>
  <tbody>${tRows}</tbody>
</table>

<div class="p-foot">Powered by Dux DigiTech</div>

</div>
<script>window.onload=function(){window.print()}<\/script>
</body>
</html>`);
		win.document.close();
	}
}

/* ── Utilities ──────────────────────────────────────────────────── */
function _gel(id){ return document.getElementById(id); }

function _fmt(val){
	return new Intl.NumberFormat("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2}).format(val||0);
}

function _bal(val,type){
	if(!val) return '<span style="color:#9ca3af;font-family:monospace">0.00</span>';
	var cls=type==="Dr"?"pl-bal-dr":"pl-bal-cr";
	return `<span class="${cls}">${_fmt(val)}<span class="pl-bsuf">${type}</span></span>`;
}

function _pill(vtype){
	var m={"Payment Voucher":"pl-pill-pv","Receipt Voucher":"pl-pill-rv","Journal Entry":"pl-pill-jv","Contra Entry":"pl-pill-cv","Payment Entry":"pl-pill-pv","Receipt Entry":"pl-pill-rv","Purchase Invoice":"pl-pill-pi","Sales Invoice":"pl-pill-si"};
	return `<span class="pl-pill ${m[vtype]||"pl-pill-other"}">${_esc(vtype)}</span>`;
}

function _esc(str){
	if(str===null||str===undefined) return "";
	return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function _debounce(fn,ms){
	var t;
	return function(){ var c=this,a=arguments; clearTimeout(t); t=setTimeout(function(){fn.apply(c,a);},ms); };
}

})();

