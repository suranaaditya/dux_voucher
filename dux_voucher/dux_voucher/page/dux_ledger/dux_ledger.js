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
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
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
		this.wrapper   = wrapper;
		this.page      = page;
		this._selected = null;
		this._lastData = null;
		this._companies = [];   // populated by _loadCompanies

		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();
	}

	_injectStyles() {
		if (document.getElementById("dl-styles")) return;
		var s = document.createElement("style");
		s.id = "dl-styles";
		s.textContent = `
.dl-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.dl-filter-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px 24px;margin-bottom:20px;display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px}
.dl-fg{display:flex;flex-direction:column;gap:5px}
.dl-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.dl-fg select,.dl-fg input[type=text],.dl-fg input[type=date]{height:36px;border:1px solid #e5e7eb;border-radius:7px;padding:0 11px;font-size:13px;color:#111827;background:#fff;outline:none;transition:border .15s;font-family:inherit;box-sizing:border-box}
.dl-fg select:focus,.dl-fg input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.08)}
#dl-co-inp{min-width:220px}
#dl-acc-inp{min-width:280px}
#dl-from,#dl-to{width:148px}
.dl-fg-co{position:relative}
/* top:100% pins the dropdown to the bottom of its .dl-fg-* container.
   The previous top:auto relied on the browser's "static position"
   computation for absolute-inside-flex-column, which Chrome resolves
   to 0 — the dropdown rendered on top of the label instead of below
   the input. */
.dl-drop{position:absolute;z-index:9999;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.12);min-width:340px;max-height:300px;overflow-y:auto;margin-top:3px;top:100%;left:0}
/* Company picker dropdown — narrower so it doesn't bleed into the Account / Party column to its right. */
#dl-co-drop{min-width:240px}
.dl-drop-section{padding:6px 12px 3px;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid #f3f4f6;background:#fafafa}
.dl-drop-item{padding:9px 14px;cursor:pointer;display:flex;flex-direction:column;gap:2px;border-bottom:1px solid #f9fafb}
.dl-drop-item:last-child{border-bottom:none}
.dl-drop-item:hover{background:#f0f4ff}
.dl-drop-label{font-size:13px;font-weight:500;color:#111827}
.dl-drop-meta{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace}
.dl-drop-empty{padding:16px;font-size:13px;color:#9ca3af;text-align:center}
.dl-fg-acc{position:relative}
.dl-sel-pill{display:inline-flex;align-items:center;gap:5px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:5px;padding:2px 8px;font-size:12px;font-weight:500;color:#1d4ed8;margin-bottom:4px;cursor:pointer}
.dl-sel-pill-x{font-size:14px;line-height:1;color:#93c5fd;margin-left:2px}
.dl-sel-pill-x:hover{color:#1d4ed8}
.dl-btn-row{display:flex;gap:8px;align-items:flex-end}
.dl-btn{height:36px;padding:0 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;font-family:inherit;transition:all .15s}
.dl-btn-primary{background:#2563eb;border-color:#2563eb;color:#fff}
.dl-btn-primary:hover{background:#1d4ed8}
.dl-btn-secondary{background:#fff;color:#374151}
.dl-btn-secondary:hover{background:#f9fafb}
.dl-print-split{display:none;position:relative}
.dl-print-split-inner{display:flex;border:1px solid #e5e7eb;border-radius:7px;overflow:hidden}
.dl-print-main{height:36px;padding:0 14px;font-size:13px;font-weight:600;cursor:pointer;border:none;border-right:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:background .15s;display:flex;align-items:center;gap:6px}
.dl-print-main:hover{background:#f9fafb}
.dl-print-caret{height:36px;width:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;background:#fff;color:#9ca3af;font-family:inherit;transition:background .15s}
.dl-print-caret:hover{background:#f3f4f6;color:#374151}
.dl-print-menu{position:absolute;right:0;top:40px;background:#fff;border:1px solid #e5e7eb;border-radius:7px;box-shadow:0 8px 24px rgba(0,0,0,.1);min-width:170px;z-index:100;display:none}
.dl-print-menu.open{display:block}
.dl-print-opt{padding:10px 14px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:9px;color:#374151;border-bottom:1px solid #f3f4f6}
.dl-print-opt:last-child{border-bottom:none}
.dl-print-opt:hover{background:#f0f4ff;color:#1d4ed8}
.dl-excel-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #16a34a;background:#16a34a;color:#fff;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.dl-excel-btn:hover{background:#15803d;border-color:#15803d}
.dl-placeholder{text-align:center;padding:64px 20px;color:#9ca3af;font-size:14px}
.dl-placeholder strong{color:#6b7280}
.dl-report-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
.dl-rpt-hdr{padding:18px 24px 14px;border-bottom:1px solid #f3f4f6}
.dl-rpt-co{font-size:16px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.01em}
.dl-rpt-ledger-row{display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;margin-bottom:4px}
.dl-rpt-ledger-row strong{font-weight:600}
.dl-acc-type-badge{font-size:10px;font-weight:700;background:#eff6ff;color:#2563eb;border-radius:4px;padding:2px 7px;letter-spacing:.03em}
.dl-party-badge{font-size:10px;font-weight:700;background:#f0fdf4;color:#166534;border-radius:4px;padding:2px 7px;letter-spacing:.03em}
.dl-rpt-period{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace;display:flex;align-items:center;gap:8px}
.dl-rpt-period span{background:#f9fafb;border:1px solid #f3f4f6;border-radius:4px;padding:1px 7px}
.dl-tbl-wrap{overflow-x:auto}
.dl-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.dl-tbl thead th{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;padding:9px 16px;background:#fafafa;border-bottom:1px solid #f3f4f6;white-space:nowrap;font-family:inherit}
.dl-tbl thead th.r{text-align:right}
.dl-tr-ob td,.dl-tr-cb td{padding:10px 16px;background:#f9fafb;font-size:12px}
.dl-tr-ob td{border-bottom:1px solid #f3f4f6}
.dl-tr-cb td{border-top:2px solid #e5e7eb}
.dl-ob-label,.dl-cb-label{font-weight:700;color:#374151;text-transform:uppercase;font-size:10px;letter-spacing:.08em}
.dl-tr-e td{padding:10px 16px;border-bottom:1px solid #f9fafb;vertical-align:top}
.dl-tr-e:hover td{background:#fafbff}
.dl-tr-r td{padding:1px 16px 9px 32px;border-bottom:1px solid #f9fafb;font-size:11px;color:#9ca3af;font-style:italic;line-height:1.5}
.dl-tr-tot td{padding:10px 16px;border-top:2px solid #e5e7eb;font-size:12.5px;font-weight:700}
.dl-tot-label{text-align:right;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;font-weight:700}
.dl-c-date{width:80px;color:#9ca3af;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px}
.dl-c-part{min-width:180px}
.dl-c-vt{width:130px;white-space:nowrap}
.dl-c-vno{width:130px;white-space:nowrap}
.dl-c-amt{width:110px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.dl-c-bal{width:120px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.dl-to{color:#2563eb;font-weight:700;font-size:11px;margin-right:4px}
.dl-by{color:#059669;font-weight:700;font-size:11px;margin-right:4px}
.dl-contra-name{color:#111827;font-weight:500;font-size:13px}
.dl-vno{color:#2563eb;text-decoration:none;font-size:12px;font-family:'SFMono-Regular',Consolas,monospace}
.dl-vno:hover{text-decoration:underline}
.dl-dr{color:#dc2626;font-weight:500}
.dl-cr{color:#059669;font-weight:500}
.dl-nil{color:#d1d5db}
.dl-bal-dr{color:#dc2626;font-weight:700}
.dl-bal-cr{color:#059669;font-weight:700}
.dl-bsuf{font-size:9px;margin-left:2px;font-weight:700;opacity:.65;letter-spacing:.04em}
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

	_renderLayout() {
		$(this.wrapper).find(".layout-main-section").html(`
<div class="dl-wrap">
  <div class="dl-filter-card">
    <div class="dl-fg dl-fg-co">
      <label>Company</label>
      <div id="dl-co-pill-wrap"></div>
      <input id="dl-co-inp" type="text" placeholder="Type to search company…" autocomplete="off">
      <input id="dl-co-sel" type="hidden">
      <div class="dl-drop" id="dl-co-drop" style="display:none"></div>
    </div>
    <div class="dl-fg dl-fg-acc">
      <label>Account / Party</label>
      <div id="dl-sel-pill-wrap"></div>
      <input id="dl-acc-inp" type="text" placeholder="Type to search accounts, suppliers, customers…" autocomplete="off">
      <div class="dl-drop" id="dl-drop" style="display:none"></div>
    </div>
    <div class="dl-fg"><label>From</label><input id="dl-from" type="date"></div>
    <div class="dl-fg"><label>To</label><input id="dl-to" type="date"></div>
    <div class="dl-btn-row">
      <button class="dl-btn dl-btn-primary" id="dl-show-btn">Show</button>
      <button class="dl-excel-btn" id="dl-excel-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M8 13l3 3-3 3M14 13l-3 3 3 3"/></svg>Excel
      </button>
      <div class="dl-print-split" id="dl-print-split">
        <div class="dl-print-split-inner">
          <button class="dl-print-main" id="dl-print-p-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Print
          </button>
          <button class="dl-print-caret" id="dl-print-caret">
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div class="dl-print-menu" id="dl-print-menu">
          <div class="dl-print-opt" id="dl-opt-p">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Portrait (A4)
          </div>
          <div class="dl-print-opt" id="dl-opt-l">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>Landscape (A4)
          </div>
        </div>
      </div>
    </div>
  </div>
  <div id="dl-area">
    <div class="dl-placeholder">Select a company and account / party, then click <strong>Show</strong>.</div>
  </div>
</div>`);
	}

	_bindEvents() {
		var self = this;
		// Company picker — type-to-filter; click-to-select stays in
		// _renderCompanyDropdown.
		_gel("dl-co-inp").addEventListener("input", function(){
			self._renderCompanyDropdown(this.value);
		});
		_gel("dl-co-inp").addEventListener("focus", function(){
			self._renderCompanyDropdown(this.value);
		});
		// Account / party picker (unchanged).
		_gel("dl-acc-inp").addEventListener("input", _debounce(function(){
			var co=_gel("dl-co-sel").value, txt=this.value.trim();
			if(co&&txt.length>=2) self._search(co,txt);
			else _gel("dl-drop").style.display="none";
		},280));
		_gel("dl-acc-inp").addEventListener("focus", function(){
			var co=_gel("dl-co-sel").value, txt=this.value.trim();
			if(co&&txt.length>=2) self._search(co,txt);
		});
		document.addEventListener("click", function(e){
			if(!e.target.closest(".dl-fg-co"))  _gel("dl-co-drop").style.display="none";
			if(!e.target.closest(".dl-fg-acc")) _gel("dl-drop").style.display="none";
			if(!e.target.closest(".dl-print-split")) _gel("dl-print-menu").classList.remove("open");
		});
		_gel("dl-show-btn").addEventListener("click", function(){ self.fetchReport(); });
		_gel("dl-excel-btn").addEventListener("click", function(){ self._exportExcel(); });
		_gel("dl-print-p-btn").addEventListener("click", function(){ _gel("dl-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("dl-print-caret").addEventListener("click", function(e){ e.stopPropagation(); _gel("dl-print-menu").classList.toggle("open"); });
		_gel("dl-opt-p").addEventListener("click",  function(){ _gel("dl-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("dl-opt-l").addEventListener("click",  function(){ _gel("dl-print-menu").classList.remove("open"); self._printReport(true); });
		["dl-co-inp","dl-acc-inp","dl-from","dl-to"].forEach(function(id){
			_gel(id).addEventListener("keydown", function(ev){ if(ev.key==="Enter") self.fetchReport(); });
		});
	}

	_setDefaultDates() {
		var now=new Date(), m=now.getMonth(), yr=now.getFullYear();
		var fy=m>=3?yr:yr-1;
		_gel("dl-from").value=fy+"-04-01";
		_gel("dl-to").value=now.toISOString().split("T")[0];
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
		var self=this, drop=_gel("dl-co-drop");
		var lc=(filterTxt||"").toLowerCase();
		var matched=this._companies.filter(function(c){ return c.toLowerCase().indexOf(lc)!==-1; });
		if(!matched.length){
			drop.innerHTML='<div class="dl-drop-empty">No companies match</div>';
			drop.style.display="block";
			return;
		}
		drop.innerHTML=matched.map(function(c){
			return `<div class="dl-drop-item dl-co-item" data-v="${_esc(c)}"><span class="dl-drop-label">${_esc(c)}</span></div>`;
		}).join("");
		drop.style.display="block";
		drop.querySelectorAll(".dl-co-item").forEach(function(el){
			el.addEventListener("click", function(){ self._selectCompany(el.dataset.v); });
		});
	}

	_selectCompany(name){
		var self=this;
		_gel("dl-co-sel").value=name;
		_gel("dl-co-inp").value="";
		_gel("dl-co-inp").placeholder="Selected ↑ — type to change";
		_gel("dl-co-drop").style.display="none";
		_gel("dl-co-pill-wrap").innerHTML=
			`<div class="dl-sel-pill">${_esc(name)}<span class="dl-sel-pill-x" id="dl-co-clear">×</span></div>`;
		_gel("dl-co-clear").addEventListener("click", function(){ self._clearCompany(); });
		// Account / party choice is company-scoped — wipe it so the
		// user re-picks one valid in the new company.
		this._clearSelection();
	}

	_clearCompany(){
		_gel("dl-co-sel").value="";
		_gel("dl-co-inp").value="";
		_gel("dl-co-inp").placeholder="Type to search company…";
		_gel("dl-co-pill-wrap").innerHTML="";
		_gel("dl-co-drop").style.display="none";
		this._clearSelection();
	}

	_clearSelection(){
		this._selected=null;
		_gel("dl-acc-inp").value="";
		_gel("dl-acc-inp").placeholder="Type to search accounts, suppliers, customers…";
		_gel("dl-sel-pill-wrap").innerHTML="";
		_gel("dl-drop").style.display="none";
	}

	_selectItem(item){
		var self=this;
		this._selected=item;
		_gel("dl-acc-inp").value="";
		_gel("dl-acc-inp").placeholder="Selected ↑ — type to change";
		_gel("dl-drop").style.display="none";
		_gel("dl-sel-pill-wrap").innerHTML=
			`<div class="dl-sel-pill">${_esc(item.label)}<span class="dl-sel-pill-x" id="dl-clear-sel">×</span></div>`;
		document.getElementById("dl-clear-sel").addEventListener("click",function(){ self._clearSelection(); });
	}

	_search(company, txt){
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.search_ledger",
			args:{company:company,search_txt:txt},
			callback:function(r){
				var results=r.message||[], drop=_gel("dl-drop");
				if(!results.length){ drop.innerHTML='<div class="dl-drop-empty">No matches found</div>'; drop.style.display="block"; return; }
				var acc=results.filter(function(x){return x.type==="account";}),
				    par=results.filter(function(x){return x.type==="party";});
				var html="";
				if(acc.length){ html+='<div class="dl-drop-section">Accounts</div>'+acc.map(function(i){ return `<div class="dl-drop-item" data-v='${JSON.stringify(i).replace(/'/g,"&#39;")}'><span class="dl-drop-label">${_esc(i.label)}</span><span class="dl-drop-meta">${_esc(i.meta)}</span></div>`; }).join(""); }
				if(par.length){ html+='<div class="dl-drop-section">Parties</div>'+par.map(function(i){ return `<div class="dl-drop-item" data-v='${JSON.stringify(i).replace(/'/g,"&#39;")}'><span class="dl-drop-label">${_esc(i.label)}</span><span class="dl-drop-meta">${_esc(i.meta)}</span></div>`; }).join(""); }
				drop.innerHTML=html; drop.style.display="block";
				drop.querySelectorAll(".dl-drop-item").forEach(function(el){
					el.addEventListener("click",function(){ var item=JSON.parse(el.dataset.v); self._selectItem(item); self.fetchReport(); });
				});
			},
		});
	}

	applyRouteOptions(opts){
		if(opts.company)   this._selectCompany(opts.company);
		if(opts.account)   _gel("dl-acc-inp").value=opts.account;
		if(opts.from_date) _gel("dl-from").value=opts.from_date;
		if(opts.to_date)   _gel("dl-to").value=opts.to_date;
		if(opts.company&&opts.account) this.fetchReport();
	}

	fetchReport(){
		var company=_gel("dl-co-sel").value,
		    from_date=_gel("dl-from").value,
		    to_date=_gel("dl-to").value;
		var account="",party=null,party_type=null;
		if(this._selected){
			if(this._selected.type==="account"){ account=this._selected.value; }
			else{ account=this._selected.account; party=this._selected.value; party_type=this._selected.party_type; }
		} else { account=_gel("dl-acc-inp").value.trim(); }
		if(!company){ frappe.msgprint({message:"Please select a Company.",indicator:"orange"}); return; }
		if(!account){ frappe.msgprint({message:"Please select an Account or Party.",indicator:"orange"}); return; }
		if(!from_date||!to_date){ frappe.msgprint({message:"Please set both dates.",indicator:"orange"}); return; }
		_gel("dl-area").innerHTML='<div class="dl-placeholder">Loading…</div>';
		_gel("dl-print-split").style.display="none";
		_gel("dl-excel-btn").style.display="none";
		this._lastData=null;
		var self=this, args={company,account,from_date,to_date};
		if(party)      args.party=party;
		if(party_type) args.party_type=party_type;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_ledger_statement",
			args:args,
			callback:function(r){
				if(r.message){ self._lastData=r.message; self._render(r.message); _gel("dl-print-split").style.display="block"; _gel("dl-excel-btn").style.display="inline-flex"; }
				else{ _gel("dl-area").innerHTML='<div class="dl-placeholder">No data found for this selection and period.</div>'; }
			},
			error:function(){ _gel("dl-area").innerHTML='<div class="dl-placeholder" style="color:#dc2626">Could not load report. Verify account name and try again.</div>'; },
		});
	}

	_render(d){
		var rows="";
		rows+=`<tr class="dl-tr-ob"><td colspan="4"><span class="dl-ob-label">Opening Balance</span></td><td class="dl-c-amt">${d.opening_debit>0?`<span class="dl-dr">${_fmt(d.opening_debit)}</span>`:'<span class="dl-nil">—</span>'}</td><td class="dl-c-amt">${d.opening_credit>0?`<span class="dl-cr">${_fmt(d.opening_credit)}</span>`:'<span class="dl-nil">—</span>'}</td><td class="dl-c-bal">${_bal(d.opening_balance,d.opening_type)}</td></tr>`;
		if(!d.rows.length) rows+=`<tr><td colspan="7" class="dl-placeholder" style="padding:32px">No transactions in this period.</td></tr>`;
		d.rows.forEach(function(row){
			var pCls=row.prefix==="To"?"dl-to":"dl-by";
			var drHtml=row.debit>0?`<span class="dl-dr">${_fmt(row.debit)}</span>`:`<span class="dl-nil">—</span>`;
			var crHtml=row.credit>0?`<span class="dl-cr">${_fmt(row.credit)}</span>`:`<span class="dl-nil">—</span>`;
			rows+=`<tr class="dl-tr-e"><td class="dl-c-date">${_esc(row.posting_date)}</td><td class="dl-c-part"><span class="${pCls}">${row.prefix}</span><span class="dl-contra-name">${_esc(row.contra)}</span></td><td class="dl-c-vt">${_pill(row.voucher_type)}</td><td class="dl-c-vno"><a class="dl-vno" href="${_esc(row.voucher_url)}" target="_blank">${_esc(row.voucher_no)}</a></td><td class="dl-c-amt">${drHtml}</td><td class="dl-c-amt">${crHtml}</td><td class="dl-c-bal">${_bal(row.balance,row.balance_type)}</td></tr>`;
			if(row.remarks) rows+=`<tr class="dl-tr-r"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
		});
		rows+=`<tr class="dl-tr-cb"><td colspan="4"><span class="dl-cb-label">Closing Balance</span></td><td class="dl-c-amt">${d.closing_balancing_debit>0?`<span class="dl-dr">${_fmt(d.closing_balancing_debit)}</span>`:'<span class="dl-nil">—</span>'}</td><td class="dl-c-amt">${d.closing_balancing_credit>0?`<span class="dl-cr">${_fmt(d.closing_balancing_credit)}</span>`:'<span class="dl-nil">—</span>'}</td><td class="dl-c-bal" style="font-size:13px">${_bal(d.closing_balance,d.closing_type)}</td></tr>`;
		rows+=`<tr class="dl-tr-tot"><td colspan="4" class="dl-tot-label">Total</td><td class="dl-c-amt"><span class="dl-dr">${_fmt(d.grand_total_debit)}</span></td><td class="dl-c-amt"><span class="dl-cr">${_fmt(d.grand_total_credit)}</span></td><td class="dl-c-bal"></td></tr>`;
		var isParty=["Customer","Supplier","Employee"].includes(d.account_type);
		var badge=d.account_type?`<span class="${isParty?"dl-party-badge":"dl-acc-type-badge"}">${_esc(d.account_type)}</span>`:"";
		_gel("dl-area").innerHTML=`
<div class="dl-report-card">
  <div class="dl-rpt-hdr">
    <div class="dl-rpt-co">${_esc(d.company)}</div>
    <div class="dl-rpt-ledger-row"><span>Ledger:</span><strong>${_esc(d.account_name)}</strong>${badge}</div>
    <div class="dl-rpt-period"><span>${_esc(d.from_date)}</span><span style="color:#d1d5db">→</span><span>${_esc(d.to_date)}</span><span style="color:#d1d5db">·</span><span>${d.row_count} transaction${d.row_count!==1?"s":""}</span></div>
  </div>
  <div class="dl-tbl-wrap">
    <table class="dl-tbl">
      <thead><tr>
        <th class="dl-c-date">Date</th><th class="dl-c-part">Particulars</th>
        <th class="dl-c-vt">Vch Type</th><th class="dl-c-vno">Vch No</th>
        <th class="dl-c-amt r">Debit</th><th class="dl-c-amt r">Credit</th>
        <th class="dl-c-bal r">Balance</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
	}

	/* ══════════════════════════════════════════════════════════
	   Excel export — streams styled .xlsx via openpyxl backend
	   ══════════════════════════════════════════════════════════ */
	_exportExcel(){
		if(!this._lastData) return;
		var company=_gel("dl-co-sel").value,
		    from_date=_gel("dl-from").value,
		    to_date=_gel("dl-to").value;
		var account="",party=null,party_type=null;
		if(this._selected){
			if(this._selected.type==="account"){ account=this._selected.value; }
			else{ account=this._selected.account; party=this._selected.value; party_type=this._selected.party_type; }
		} else { account=_gel("dl-acc-inp").value.trim(); }
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
		var d=this._lastData;
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
			<td class="p-num">${d.opening_debit>0?`<span class="p-dr">${_fmt(d.opening_debit)}</span>`:'<span class="p-nil">—</span>'}</td>
			<td class="p-num">${d.opening_credit>0?`<span class="p-cr">${_fmt(d.opening_credit)}</span>`:'<span class="p-nil">—</span>'}</td>
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
			if(row.remarks) tRows+=`<tr class="p-rmk"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
		});

		// Closing balance — carried down as a balancing contra (opposite column)
		tRows+=`<tr class="p-cb">
			<td colspan="4" class="p-ob-lbl">Closing Balance</td>
			<td class="p-num">${d.closing_balancing_debit>0?`<span class="p-dr">${_fmt(d.closing_balancing_debit)}</span>`:'<span class="p-nil">—</span>'}</td>
			<td class="p-num">${d.closing_balancing_credit>0?`<span class="p-cr">${_fmt(d.closing_balancing_credit)}</span>`:'<span class="p-nil">—</span>'}</td>
			<td class="p-num p-fw" style="font-size:12.5px;${d.closing_type==="Dr"?"color:#dc2626":"color:#16a34a"}">${_fmt(d.closing_balance)}<span class="p-suf">${d.closing_type}</span></td>
		</tr>`;

		// Totals — balanced grand total (Debit == Credit)
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
<title>Ledger Statement — ${_esc(d.account_name)}</title>
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
    <div class="p-rtype">Ledger Statement</div>
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
	var cls=type==="Dr"?"dl-bal-dr":"dl-bal-cr";
	return `<span class="${cls}">${_fmt(val)}<span class="dl-bsuf">${type}</span></span>`;
}

function _pill(vtype){
	var m={"Payment Voucher":"dl-pill-pv","Receipt Voucher":"dl-pill-rv","Journal Entry":"dl-pill-jv","Contra Entry":"dl-pill-cv","Payment Entry":"dl-pill-pv","Receipt Entry":"dl-pill-rv","Purchase Invoice":"dl-pill-pi","Sales Invoice":"dl-pill-si"};
	return `<span class="dl-pill ${m[vtype]||"dl-pill-other"}">${_esc(vtype)}</span>`;
}

function _esc(str){
	if(str===null||str===undefined) return "";
	return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}

function _debounce(fn,ms){
	var t;
	return function(){ var c=this,a=arguments; clearTimeout(t); t=setTimeout(function(){fn.apply(c,a);},ms); };
}
