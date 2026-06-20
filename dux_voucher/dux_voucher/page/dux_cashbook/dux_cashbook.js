/* ============================================================
   dux_cashbook.js  —  Cash & Bank Book
   Dux DigiTech  —  dux_voucher app
   Reuses get_ledger_statement — account picker pre-filtered
   to Bank/Cash type accounts only.
   ============================================================ */

frappe.pages["dux-cashbook"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Cash & Bank Book",
			single_column: true,
		});
		window._dux_cashbook_instance = new DuxCashBook(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
		);
		console.error("dux-cashbook:", e);
	}
};

frappe.pages["dux-cashbook"].on_page_show = function (wrapper) {
	if (window._dux_cashbook_instance && frappe.route_options) {
		window._dux_cashbook_instance.applyRouteOptions(frappe.route_options);
		frappe.route_options = null;
	}
};

/* ============================================================
   DuxCashBook
   ============================================================ */
class DuxCashBook {
	constructor(wrapper, page) {
		this.wrapper   = wrapper;
		this.page      = page;
		this._lastData = null;
		this._accounts = [];  // Bank/Cash accounts for current company
		this._companies = []; // populated by _loadCompanies
		this._showAllDetails = false;       // global "Show details" toggle
		this._expandedRows = new Set();     // per-row drill-down state

		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();
	}

	_injectStyles() {
		if (document.getElementById("cb-styles")) return;
		var s = document.createElement("style");
		s.id = "cb-styles";
		s.textContent = `
.cb-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.cb-filter-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px 24px;margin-bottom:20px;display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px}
.cb-fg{display:flex;flex-direction:column;gap:5px}
.cb-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.cb-fg select,.cb-fg input[type=date],.cb-fg input[type=text]{height:36px;border:1px solid #e5e7eb;border-radius:7px;padding:0 11px;font-size:13px;color:#111827;background:#fff;outline:none;transition:border .15s;font-family:inherit;box-sizing:border-box}
.cb-fg select:focus,.cb-fg input:focus{border-color:#059669;box-shadow:0 0 0 3px rgba(5,150,105,.08)}
#cb-co-inp{min-width:220px}
.cb-fg-co{position:relative}
.cb-drop{position:absolute;z-index:9999;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.12);min-width:240px;max-height:300px;overflow-y:auto;margin-top:3px;top:100%;left:0}
.cb-drop-item{padding:9px 14px;cursor:pointer;border-bottom:1px solid #f9fafb;font-size:13px;color:#111827}
.cb-drop-item:last-child{border-bottom:none}
.cb-drop-item:hover{background:#f0fdf4}
.cb-drop-empty{padding:16px;font-size:13px;color:#9ca3af;text-align:center}
.cb-sel-pill{display:inline-flex;align-items:center;gap:5px;background:#f0fdf4;border:1px solid #a7f3d0;border-radius:5px;padding:2px 8px;font-size:12px;font-weight:500;color:#047857;margin-bottom:4px;cursor:pointer}
.cb-sel-pill-x{font-size:14px;line-height:1;color:#6ee7b7;margin-left:2px}
.cb-sel-pill-x:hover{color:#047857}
#cb-acc-sel{min-width:280px}
#cb-from,#cb-to{width:148px}
.cb-btn-row{display:flex;gap:8px;align-items:flex-end}
.cb-btn{height:36px;padding:0 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;font-family:inherit;transition:all .15s}
.cb-btn-primary{background:#059669;border-color:#059669;color:#fff}
.cb-btn-primary:hover{background:#047857}
.cb-btn-secondary{background:#fff;color:#374151}
.cb-btn-secondary:hover{background:#f9fafb}
.cb-print-split{display:none;position:relative}
.cb-print-split-inner{display:flex;border:1px solid #e5e7eb;border-radius:7px;overflow:hidden}
.cb-print-main{height:36px;padding:0 14px;font-size:13px;font-weight:600;cursor:pointer;border:none;border-right:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:background .15s;display:flex;align-items:center;gap:6px}
.cb-print-main:hover{background:#f9fafb}
.cb-print-caret{height:36px;width:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;background:#fff;color:#9ca3af;transition:background .15s}
.cb-print-caret:hover{background:#f3f4f6;color:#374151}
.cb-print-menu{position:absolute;right:0;top:40px;background:#fff;border:1px solid #e5e7eb;border-radius:7px;box-shadow:0 8px 24px rgba(0,0,0,.1);min-width:170px;z-index:100;display:none}
.cb-print-menu.open{display:block}
.cb-print-opt{padding:10px 14px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:9px;color:#374151;border-bottom:1px solid #f3f4f6}
.cb-print-opt:last-child{border-bottom:none}
.cb-print-opt:hover{background:#f0fdf4;color:#059669}
.cb-excel-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #16a34a;background:#16a34a;color:#fff;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.cb-excel-btn:hover{background:#15803d;border-color:#15803d}
.cb-placeholder{text-align:center;padding:64px 20px;color:#9ca3af;font-size:14px}
.cb-placeholder strong{color:#6b7280}
.cb-acc-type-badge-bank{font-size:10px;font-weight:700;background:#f0fdf4;color:#166534;border-radius:4px;padding:2px 7px;letter-spacing:.03em}
.cb-acc-type-badge-cash{font-size:10px;font-weight:700;background:#fffbeb;color:#92400e;border-radius:4px;padding:2px 7px;letter-spacing:.03em}

/* Report card — identical to ledger statement but green accent */
.cb-report-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
.cb-rpt-hdr{padding:18px 24px 14px;border-bottom:1px solid #f3f4f6;border-top:3px solid #059669}
.cb-rpt-co{font-size:16px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.01em}
.cb-rpt-ledger-row{display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;margin-bottom:4px}
.cb-rpt-ledger-row strong{font-weight:600}
.cb-rpt-period{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace;display:flex;align-items:center;gap:8px}
.cb-rpt-period span{background:#f9fafb;border:1px solid #f3f4f6;border-radius:4px;padding:1px 7px}
.cb-tbl-wrap{overflow-x:auto}
.cb-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.cb-tbl thead th{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;padding:9px 16px;background:#fafafa;border-bottom:1px solid #f3f4f6;white-space:nowrap;font-family:inherit}
.cb-tbl thead th.r{text-align:right}
.cb-tr-ob td,.cb-tr-cb td{padding:10px 16px;background:#f0fdf4;font-size:12px}
.cb-tr-ob td{border-bottom:1px solid #d1fae5}
.cb-tr-cb td{border-top:2px solid #059669}
.cb-ob-label,.cb-cb-label{font-weight:700;color:#166534;text-transform:uppercase;font-size:10px;letter-spacing:.08em}
.cb-tr-e td{padding:10px 16px;border-bottom:1px solid #f9fafb;vertical-align:top}
.cb-tr-e:hover td{background:#f0fdf4}
.cb-tr-r td{padding:1px 16px 9px 32px;border-bottom:1px solid #f9fafb;font-size:11px;color:#9ca3af;font-style:italic;line-height:1.5;overflow-wrap:anywhere;word-break:break-word}
.cb-tr-tot td{padding:10px 16px;border-top:2px solid #059669;font-size:12.5px;font-weight:700}
.cb-tot-label{text-align:right;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;font-weight:700}
.cb-c-date{width:80px;color:#9ca3af;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px}
.cb-c-part{min-width:180px}
.cb-c-vt{width:130px;white-space:nowrap}
.cb-c-vno{width:130px;white-space:nowrap}
.cb-c-amt{width:110px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.cb-c-bal{width:120px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.cb-to{color:#2563eb;font-weight:700;font-size:11px;margin-right:4px}
.cb-by{color:#059669;font-weight:700;font-size:11px;margin-right:4px}
.cb-contra-name{color:#111827;font-weight:500;font-size:13px}
.cb-vno{color:#2563eb;text-decoration:none;font-size:12px;font-family:'SFMono-Regular',Consolas,monospace}
.cb-vno:hover{text-decoration:underline}
.cb-dr{color:#dc2626;font-weight:500}
.cb-cr{color:#059669;font-weight:500}
.cb-nil{color:#d1d5db}
.cb-bal-dr{color:#dc2626;font-weight:700}
.cb-bal-cr{color:#059669;font-weight:700}
.cb-bsuf{font-size:9px;margin-left:2px;font-weight:700;opacity:.65;letter-spacing:.04em}
.cb-pill{display:inline-block;font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;letter-spacing:.03em;white-space:nowrap;font-family:inherit}
.cb-pill-pv{background:#eff6ff;color:#1d4ed8}
.cb-pill-rv{background:#f0fdf4;color:#166534}
.cb-pill-jv{background:#fffbeb;color:#92400e}
.cb-pill-cv{background:#f5f3ff;color:#5b21b6}
.cb-pill-pi{background:#fff7ed;color:#c2410c}
.cb-pill-other{background:#f3f4f6;color:#4b5563;border:1px solid #e5e7eb}
.cb-detail-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.cb-detail-btn:hover{background:#f9fafb}
.cb-detail-btn.active{background:#f0fdf4;border-color:#a7f3d0;color:#047857}
.cb-chev{display:inline-block;width:13px;color:#9ca3af;font-size:10px;margin-right:3px;user-select:none}
.cb-expandable{cursor:pointer}
.cb-expandable:hover .cb-chev{color:#059669}
.cb-bd-count{color:#9ca3af;font-size:11px;margin-left:5px}
.cb-tr-bd td{padding:5px 16px;border-bottom:1px solid #f9fafb;background:#fcfcfd;font-size:11.5px;vertical-align:top}
.cb-bd-part{color:#475569;padding-left:42px!important}
.cb-bd-arrow{color:#9ca3af;margin-right:5px}
.cb-c-part,.cb-contra-name{word-break:break-word}
@media(max-width:900px){
  .cb-tbl{font-size:11.5px}
  .cb-tbl thead th{padding:8px 9px}
  .cb-tr-e td,.cb-tr-ob td,.cb-tr-cb td,.cb-tr-tot td,.cb-tr-bd td{padding:8px 9px}
  .cb-c-date{width:58px;font-size:11px}
  .cb-c-vt{width:96px}
  .cb-c-vno{width:96px}
  .cb-c-amt{width:84px}
  .cb-c-bal{width:92px}
  .cb-c-part{min-width:110px}
  .cb-tr-r td{padding-left:16px}
  .cb-bd-part{padding-left:28px!important}
}
@media(max-width:600px){
  .cb-tbl{font-size:11px}
  .cb-tbl thead th,.cb-tr-e td,.cb-tr-ob td,.cb-tr-cb td,.cb-tr-tot td,.cb-tr-bd td{padding:6px 6px}
  .cb-c-vt{width:76px}
  .cb-c-vno{width:84px}
  .cb-c-amt{width:76px}
  .cb-c-bal{width:84px}
  .cb-c-part{min-width:80px}
  .cb-pill{font-size:9px;padding:2px 5px}
}
		`;
		document.head.appendChild(s);
	}

	_renderLayout() {
		$(this.wrapper).find(".layout-main-section").html(`
<div class="cb-wrap">
  <div class="cb-filter-card">
    <div class="cb-fg cb-fg-co">
      <label>Company</label>
      <div id="cb-co-pill-wrap"></div>
      <input id="cb-co-inp" type="text" placeholder="Type to search company…" autocomplete="off">
      <input id="cb-co-sel" type="hidden">
      <div class="cb-drop" id="cb-co-drop" style="display:none"></div>
    </div>
    <div class="cb-fg">
      <label>Bank / Cash Account</label>
      <select id="cb-acc-sel"><option value="">— select company first —</option></select>
    </div>
    <div class="cb-fg"><label>From</label><input id="cb-from" type="date"></div>
    <div class="cb-fg"><label>To</label><input id="cb-to" type="date"></div>
    <div class="cb-btn-row">
      <button class="cb-btn cb-btn-primary" id="cb-show-btn">Show</button>
      <button class="cb-excel-btn" id="cb-excel-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M8 13l3 3-3 3M14 13l-3 3 3 3"/></svg>Excel
      </button>
      <button class="cb-detail-btn" id="cb-detail-btn" title="Expand every 'Various' row into its individual heads">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg><span class="cb-detail-lbl">Show details</span>
      </button>
      <div class="cb-print-split" id="cb-print-split">
        <div class="cb-print-split-inner">
          <button class="cb-print-main" id="cb-print-p-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Print
          </button>
          <button class="cb-print-caret" id="cb-print-caret">
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div class="cb-print-menu" id="cb-print-menu">
          <div class="cb-print-opt" id="cb-opt-p">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Portrait (A4)
          </div>
          <div class="cb-print-opt" id="cb-opt-l">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>Landscape (A4)
          </div>
        </div>
      </div>
    </div>
  </div>
  <div id="cb-area">
    <div class="cb-placeholder">Select a company and bank/cash account, then click <strong>Show</strong>.</div>
  </div>
</div>`);
	}

	_bindEvents() {
		var self = this;
		_gel("cb-co-inp").addEventListener("input", function(){ self._renderCompanyDropdown(this.value); });
		_gel("cb-co-inp").addEventListener("focus", function(){ self._renderCompanyDropdown(this.value); });
		document.addEventListener("click", function(e){
			if(!e.target.closest(".cb-fg-co"))      _gel("cb-co-drop").style.display="none";
			if(!e.target.closest(".cb-print-split")) _gel("cb-print-menu").classList.remove("open");
		});
		_gel("cb-show-btn").addEventListener("click",   function(){ self.fetchReport(); });
		_gel("cb-excel-btn").addEventListener("click",  function(){ self._exportExcel(); });
		_gel("cb-detail-btn").addEventListener("click", function(){ self._toggleAllDetails(); });
		_gel("cb-print-p-btn").addEventListener("click",function(){ _gel("cb-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("cb-print-caret").addEventListener("click",function(e){ e.stopPropagation(); _gel("cb-print-menu").classList.toggle("open"); });
		_gel("cb-opt-p").addEventListener("click",  function(){ _gel("cb-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("cb-opt-l").addEventListener("click",  function(){ _gel("cb-print-menu").classList.remove("open"); self._printReport(true); });
		["cb-co-inp","cb-acc-sel","cb-from","cb-to"].forEach(function(id){
			_gel(id).addEventListener("keydown", function(ev){ if(ev.key==="Enter") self.fetchReport(); });
		});
	}

	_setDefaultDates() {
		var now=new Date(), m=now.getMonth(), yr=now.getFullYear();
		var today=now.toISOString().split("T")[0];
		_gel("cb-from").value=today;
		_gel("cb-to").value=today;
	}

	_loadCompanies() {
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_permitted_companies",
			callback:function(r){
				self._companies = r.message || [];
				if(self._companies.length === 1) self._selectCompany(self._companies[0]);
			},
		});
	}

	_renderCompanyDropdown(filterTxt){
		var self=this, drop=_gel("cb-co-drop");
		var lc=(filterTxt||"").toLowerCase();
		var matched=this._companies.filter(function(c){ return c.toLowerCase().indexOf(lc)!==-1; });
		if(!matched.length){
			drop.innerHTML='<div class="cb-drop-empty">No companies match</div>';
			drop.style.display="block";
			return;
		}
		drop.innerHTML=matched.map(function(c){
			return `<div class="cb-drop-item cb-co-item" data-v="${cbEsc(c)}">${cbEsc(c)}</div>`;
		}).join("");
		drop.style.display="block";
		drop.querySelectorAll(".cb-co-item").forEach(function(el){
			el.addEventListener("click", function(){ self._selectCompany(el.dataset.v); });
		});
	}

	_selectCompany(name){
		var self=this;
		_gel("cb-co-sel").value=name;
		_gel("cb-co-inp").value="";
		_gel("cb-co-inp").placeholder="Selected ↑ — type to change";
		_gel("cb-co-drop").style.display="none";
		_gel("cb-co-pill-wrap").innerHTML=
			`<div class="cb-sel-pill">${cbEsc(name)}<span class="cb-sel-pill-x" id="cb-co-clear">×</span></div>`;
		_gel("cb-co-clear").addEventListener("click", function(){ self._clearCompany(); });
		// Cash Book's bank/cash account picker is company-scoped — reload it.
		_gel("cb-acc-sel").innerHTML = '<option value="">Loading…</option>';
		_gel("cb-print-split").style.display = "none";
		self._loadAccounts(name);
	}

	_clearCompany(){
		_gel("cb-co-sel").value="";
		_gel("cb-co-inp").value="";
		_gel("cb-co-inp").placeholder="Type to search company…";
		_gel("cb-co-pill-wrap").innerHTML="";
		_gel("cb-co-drop").style.display="none";
		_gel("cb-acc-sel").innerHTML='<option value="">— select company first —</option>';
	}

	_loadAccounts(company){
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_bank_cash_accounts",
			args:{company:company},
			callback:function(r){
				var accounts=r.message||[];
				self._accounts=accounts;
				var sel=_gel("cb-acc-sel");
				sel.innerHTML='<option value="">Select account…</option>';
				var lastType="";
				accounts.forEach(function(a){
					// Add optgroup-style label when type changes
					if(a.account_type!==lastType){
						sel.innerHTML+=`<option disabled style="font-weight:700;color:#6b7280">── ${cbEsc(a.account_type)} Accounts ──</option>`;
						lastType=a.account_type;
					}
					sel.innerHTML+=`<option value="${cbEsc(a.name)}">${cbEsc(a.account_name)}</option>`;
				});
				if(!accounts.length){
					sel.innerHTML='<option value="">No Bank/Cash accounts found</option>';
				}
			},
		});
	}

	applyRouteOptions(opts){
		if(opts.company)   this._selectCompany(opts.company);
		if(opts.account)   _gel("cb-acc-sel").value=opts.account;
		if(opts.from_date) _gel("cb-from").value=opts.from_date;
		if(opts.to_date)   _gel("cb-to").value=opts.to_date;
		if(opts.company)   this.fetchReport();
	}

	fetchReport(){
		var company   = _gel("cb-co-sel").value;
		var account   = _gel("cb-acc-sel").value;
		var from_date = _gel("cb-from").value;
		var to_date   = _gel("cb-to").value;

		if(!company)  { frappe.msgprint({message:"Please select a Company.",indicator:"orange"}); return; }
		if(!account)  { frappe.msgprint({message:"Please select a Bank/Cash Account.",indicator:"orange"}); return; }
		if(!from_date||!to_date){ frappe.msgprint({message:"Please set both dates.",indicator:"orange"}); return; }

		_gel("cb-area").innerHTML='<div class="cb-placeholder">Loading…</div>';
		_gel("cb-print-split").style.display="none";
		_gel("cb-excel-btn").style.display="none";
		this._lastData=null;

		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_ledger_statement",
			args:{company, account, from_date, to_date},
			callback:function(r){
				if(r.message){
					self._lastData=r.message;
					self._render(r.message);
					_gel("cb-print-split").style.display="block";
					_gel("cb-excel-btn").style.display="inline-flex";
				} else {
					_gel("cb-area").innerHTML='<div class="cb-placeholder">No transactions found for this account and period.</div>';
				}
			},
			error:function(){ _gel("cb-area").innerHTML='<div class="cb-placeholder" style="color:#dc2626">Could not load Cash Book. Try again.</div>'; },
		});
	}

	_render(d){
		var self=this;
		// Fresh data — start collapsed.
		this._showAllDetails=false;
		this._expandedRows=new Set();
		var rows="";
		var isBank = d.account_type === "Bank";
		var badgeClass = isBank ? "cb-acc-type-badge-bank" : "cb-acc-type-badge-cash";

		rows+=`<tr class="cb-tr-ob"><td colspan="4"><span class="cb-ob-label">Opening Balance</span></td><td class="cb-c-amt">${d.opening_debit>0?`<span class="cb-dr">${cbFmt(d.opening_debit)}</span>`:'<span class="cb-nil">—</span>'}</td><td class="cb-c-amt">${d.opening_credit>0?`<span class="cb-cr">${cbFmt(d.opening_credit)}</span>`:'<span class="cb-nil">—</span>'}</td><td class="cb-c-bal">${cbBal(d.opening_balance,d.opening_type)}</td></tr>`;

		if(!d.rows.length) rows+=`<tr><td colspan="7" class="cb-placeholder" style="padding:32px">No transactions in this period.</td></tr>`;

		d.rows.forEach(function(row,i){
			var pCls=row.prefix==="To"?"cb-to":"cb-by";
			var drHtml=row.debit>0?`<span class="cb-dr">${cbFmt(row.debit)}</span>`:`<span class="cb-nil">—</span>`;
			var crHtml=row.credit>0?`<span class="cb-cr">${cbFmt(row.credit)}</span>`:`<span class="cb-nil">—</span>`;
			var hasBd=row.breakdown&&row.breakdown.length;
			var chev=hasBd?`<span class="cb-chev">▸</span>`:"";
			var cnt=hasBd?`<span class="cb-bd-count">(${row.breakdown.length})</span>`:"";
			rows+=`<tr class="cb-tr-e${hasBd?" cb-expandable":""}" data-r="${i}">
				<td class="cb-c-date">${cbEsc(row.posting_date)}</td>
				<td class="cb-c-part">${chev}<span class="${pCls}">${row.prefix}</span><span class="cb-contra-name">${cbEsc(row.contra)}</span>${cnt}</td>
				<td class="cb-c-vt">${cbPill(row.voucher_type)}</td>
				<td class="cb-c-vno"><a class="cb-vno" href="${cbEsc(row.voucher_url)}" target="_blank">${cbEsc(row.voucher_no)}</a></td>
				<td class="cb-c-amt">${drHtml}</td>
				<td class="cb-c-amt">${crHtml}</td>
				<td class="cb-c-bal">${cbBal(row.balance,row.balance_type)}</td>
			</tr>`;
			if(hasBd){
				row.breakdown.forEach(function(b){
					var amtCells=b.side==="Cr"
						?`<td class="cb-c-amt"></td><td class="cb-c-amt"><span class="cb-cr">${cbFmt(b.amount)}</span></td>`
						:`<td class="cb-c-amt"><span class="cb-dr">${cbFmt(b.amount)}</span></td><td class="cb-c-amt"></td>`;
					rows+=`<tr class="cb-tr-bd" data-bd="${i}" style="display:none"><td class="cb-c-date"></td><td class="cb-c-part cb-bd-part"><span class="cb-bd-arrow">↳</span>${cbEsc(b.label)}</td><td class="cb-c-vt"></td><td class="cb-c-vno"></td>${amtCells}<td class="cb-c-bal"></td></tr>`;
				});
			}
			if(row.remarks) rows+=`<tr class="cb-tr-r"><td colspan="7">${cbEsc(row.remarks)}</td></tr>`;
		});

		rows+=`<tr class="cb-tr-cb"><td colspan="4"><span class="cb-cb-label">Closing Balance</span></td><td class="cb-c-amt">${d.closing_balancing_debit>0?`<span class="cb-dr">${cbFmt(d.closing_balancing_debit)}</span>`:'<span class="cb-nil">—</span>'}</td><td class="cb-c-amt">${d.closing_balancing_credit>0?`<span class="cb-cr">${cbFmt(d.closing_balancing_credit)}</span>`:'<span class="cb-nil">—</span>'}</td><td class="cb-c-bal" style="font-size:13px">${cbBal(d.closing_balance,d.closing_type)}</td></tr>`;
		rows+=`<tr class="cb-tr-tot"><td colspan="4" class="cb-tot-label">Total</td><td class="cb-c-amt"><span class="cb-dr">${cbFmt(d.grand_total_debit)}</span></td><td class="cb-c-amt"><span class="cb-cr">${cbFmt(d.grand_total_credit)}</span></td><td class="cb-c-bal"></td></tr>`;

		_gel("cb-area").innerHTML=`
<div class="cb-report-card">
  <div class="cb-rpt-hdr">
    <div class="cb-rpt-co">${cbEsc(d.company)}</div>
    <div class="cb-rpt-ledger-row">
      <span>${isBank?"Bank Book":"Cash Book"}:</span>
      <strong>${cbEsc(d.account_name)}</strong>
      <span class="${badgeClass}">${cbEsc(d.account_type)}</span>
    </div>
    <div class="cb-rpt-period">
      <span>${cbEsc(d.from_date)}</span><span style="color:#d1d5db">→</span><span>${cbEsc(d.to_date)}</span>
      <span style="color:#d1d5db">·</span><span>${d.row_count} transaction${d.row_count!==1?"s":""}</span>
    </div>
  </div>
  <div class="cb-tbl-wrap">
    <table class="cb-tbl">
      <thead><tr>
        <th class="cb-c-date">Date</th><th class="cb-c-part">Particulars</th>
        <th class="cb-c-vt">Vch Type</th><th class="cb-c-vno">Vch No</th>
        <th class="cb-c-amt r">Receipts (₹)</th>
        <th class="cb-c-amt r">Payments (₹)</th>
        <th class="cb-c-bal r">Balance (₹)</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
		// Show the "Show details" toggle only when something is expandable.
		var anyBd=d.rows.some(function(r){ return r.breakdown&&r.breakdown.length; });
		var dbtn=_gel("cb-detail-btn");
		if(dbtn){
			dbtn.style.display=anyBd?"inline-flex":"none";
			dbtn.classList.remove("active");
			var lbl=dbtn.querySelector(".cb-detail-lbl"); if(lbl) lbl.textContent="Show details";
		}
		this._attachDetailHandlers();
	}

	/* ── "Various" drill-down: per-row click + global toggle ─────── */
	_attachDetailHandlers(){
		var self=this, area=_gel("cb-area");
		if(!area) return;
		area.querySelectorAll(".cb-expandable").forEach(function(tr){
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
		var area=_gel("cb-area");
		area.querySelectorAll('.cb-tr-bd[data-bd="'+i+'"]').forEach(function(tr){
			tr.style.display=expanded?"":"none";
		});
		var chev=area.querySelector('.cb-expandable[data-r="'+i+'"] .cb-chev');
		if(chev) chev.textContent=expanded?"▾":"▸";
	}

	_toggleAllDetails(){
		this._showAllDetails=!this._showAllDetails;
		var self=this, area=_gel("cb-area");
		if(area) area.querySelectorAll(".cb-expandable").forEach(function(tr){
			self._applyRowVisibility(parseInt(tr.dataset.r,10));
		});
		var dbtn=_gel("cb-detail-btn");
		if(dbtn){
			dbtn.classList.toggle("active", this._showAllDetails);
			var lbl=dbtn.querySelector(".cb-detail-lbl");
			if(lbl) lbl.textContent=this._showAllDetails?"Hide details":"Show details";
		}
	}

	/* ── Excel Export ─────────────────────────────────────────────── */
	_exportExcel(){
		if(!this._lastData) return;
		var company=_gel("cb-co-sel").value,
		    account=_gel("cb-acc-sel").value,
		    from_date=_gel("cb-from").value,
		    to_date=_gel("cb-to").value;
		var params=new URLSearchParams({company:company,account:account,from_date:from_date,to_date:to_date});
		var url="/api/method/dux_voucher.dux_voucher.api.reports_export.export_cash_bank_book_xlsx?"+params.toString();
		window.location.href=url;
	}

	/* ── Professional Print ───────────────────────────────────────── */
	_printReport(landscape){
		if(!this._lastData) return;
		var self=this, d=this._lastData;
		var win=window.open("","_blank","width=1100,height=750");
		if(!win){ frappe.msgprint("Please allow pop-ups for this site."); return; }

		var pageRule=landscape
			?"@page{size:A4 landscape;margin:12mm 14mm 18mm}@page{@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);font-size:8.5px;color:#64748b;font-family:'Segoe UI',Arial,sans-serif}}"
			:"@page{size:A4 portrait;margin:16mm 12mm 18mm}@page{@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);font-size:8.5px;color:#64748b;font-family:'Segoe UI',Arial,sans-serif}}";
		var isBank=d.account_type==="Bank";
		var accentColor=isBank?"#059669":"#d97706";
		var printedDate=new Date().toLocaleDateString("en-IN",{day:"2-digit",month:"long",year:"numeric"});

		var tRows="";
		tRows+=`<tr class="p-ob"><td colspan="4" class="p-ob-lbl">Opening Balance</td><td class="p-num">${d.opening_debit>0?`<span class="p-dr">${cbFmt(d.opening_debit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num">${d.opening_credit>0?`<span class="p-cr">${cbFmt(d.opening_credit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num p-fw ${d.opening_type==="Dr"?"p-dr":"p-cr"}">${cbFmt(d.opening_balance)}<span class="p-suf">${d.opening_type}</span></td></tr>`;

		d.rows.forEach(function(row,idx){
			var kwHtml=row.prefix==="To"?'<span class="p-to">To</span>':'<span class="p-by">By</span>';
			var drHtml=row.debit>0?`<span class="p-dr">${cbFmt(row.debit)}</span>`:'<span class="p-nil">—</span>';
			var crHtml=row.credit>0?`<span class="p-cr">${cbFmt(row.credit)}</span>`:'<span class="p-nil">—</span>';
			var balCls=row.balance_type==="Dr"?"p-dr":"p-cr";
			tRows+=`<tr class="${idx%2===0?"p-even":"p-odd"}">
				<td class="p-dt">${cbEsc(row.posting_date)}</td>
				<td class="p-part">${kwHtml} ${cbEsc(row.contra)}</td>
				<td class="p-vt">${cbEsc(row.voucher_type)}</td>
				<td class="p-vno">${cbEsc(row.voucher_no)}</td>
				<td class="p-num">${drHtml}</td>
				<td class="p-num">${crHtml}</td>
				<td class="p-num p-fw ${balCls}">${cbFmt(row.balance)}<span class="p-suf">${row.balance_type}</span></td>
			</tr>`;
			if(self._showAllDetails||self._expandedRows.has(idx)){
				(row.breakdown||[]).forEach(function(b){
					var bd=b.side==="Cr"
						?`<td class="p-num"></td><td class="p-num"><span class="p-cr">${cbFmt(b.amount)}</span></td>`
						:`<td class="p-num"><span class="p-dr">${cbFmt(b.amount)}</span></td><td class="p-num"></td>`;
					tRows+=`<tr class="${idx%2===0?"p-even":"p-odd"}"><td></td><td class="p-part" style="padding-left:18px;color:#475569;font-size:9.5px">↳ ${cbEsc(b.label)}</td><td></td><td></td>${bd}<td class="p-num"></td></tr>`;
				});
			}
			if(row.remarks) tRows+=`<tr class="p-rmk"><td colspan="7">${cbEsc(row.remarks)}</td></tr>`;
		});

		tRows+=`<tr class="p-cb"><td colspan="4" class="p-ob-lbl">Closing Balance</td><td class="p-num">${d.closing_balancing_debit>0?`<span class="p-dr">${cbFmt(d.closing_balancing_debit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num">${d.closing_balancing_credit>0?`<span class="p-cr">${cbFmt(d.closing_balancing_credit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num p-fw ${d.closing_type==="Dr"?"p-dr":"p-cr"}" style="font-size:12.5px">${cbFmt(d.closing_balance)}<span class="p-suf">${d.closing_type}</span></td></tr>`;
		tRows+=`<tr class="p-tot"><td colspan="4" class="p-tot-lbl">Total</td><td class="p-num p-dr">${cbFmt(d.grand_total_debit)}</td><td class="p-num p-cr">${cbFmt(d.grand_total_credit)}</td><td class="p-num"></td></tr>`;

		win.document.write(`<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>${isBank?"Bank Book":"Cash Book"} — ${cbEsc(d.account_name)}</title>
<style>
${pageRule}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;font-size:11px;background:#fff;color:#1e293b}
.p-hdr{display:flex;justify-content:space-between;align-items:flex-end;padding-bottom:10px;margin-bottom:14px;border-bottom:3px solid #0f172a}
.p-rtype{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.18em;color:#94a3b8;margin-bottom:5px}
.p-coname{font-size:21px;font-weight:800;color:#0f172a;letter-spacing:-.4px}
.p-hdr-right{text-align:right;font-size:9px;color:#94a3b8}
.p-info{display:flex;justify-content:space-between;align-items:center;background:#f8fafc;border:1px solid #e2e8f0;border-left:4.5px solid ${accentColor};border-radius:0 6px 6px 0;padding:10px 16px;margin-bottom:16px}
.p-badge{display:inline-block;font-size:9px;font-weight:700;background:${isBank?"#f0fdf4":"#fffbeb"};color:${isBank?"#166534":"#92400e"};border-radius:3px;padding:2px 7px;letter-spacing:.05em}
.p-info-name{font-size:14px;font-weight:800;color:#0f172a;display:flex;align-items:center;gap:8px}
.p-period{font-size:10px;color:#475569;font-family:monospace;margin-bottom:2px}
.p-txncount{font-size:9px;color:#94a3b8}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
table{width:100%;border-collapse:collapse}
thead tr{background:#1e293b}
thead th{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#f1f5f9;padding:7px 9px;white-space:nowrap}
thead th.r{text-align:right}
.p-ob td,.p-cb td{background:${isBank?"#d1fae5":"#fef3c7"};padding:8px 9px;border-top:1px solid ${isBank?"#6ee7b7":"#fcd34d"};border-bottom:1px solid ${isBank?"#6ee7b7":"#fcd34d"}}
.p-cb td{border-top:2.5px solid #0f172a!important}
.p-ob-lbl{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;color:${isBank?"#166534":"#92400e"}}
.p-even td{background:#fff;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-odd  td{background:#fafbfc;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-rmk td{padding:0 9px 6px 22px;border-bottom:1px solid #f1f5f9;font-size:9px;color:#94a3b8;font-style:italic;overflow-wrap:anywhere;word-break:break-word}
.p-tot td{border-top:2.5px solid #0f172a;padding:8px 9px;font-weight:800;background:#f8fafc}
.p-tot-lbl{text-align:right;font-size:8.5px;text-transform:uppercase;letter-spacing:.1em;color:#64748b}
.p-dt{width:66px;color:#64748b;font-family:monospace;font-size:10px;white-space:nowrap}
.p-part{font-size:11px;color:#0f172a}
.p-vt{width:108px;font-size:10px;color:#374151}
.p-vno{width:118px;font-family:monospace;font-size:10px;color:#1d4ed8}
.p-num{width:94px;text-align:right;font-family:monospace;font-size:11px}
.p-fw{font-weight:700}
.p-to{color:#1d4ed8;font-weight:800;font-size:9.5px;margin-right:3px}
.p-by{color:#16a34a;font-weight:800;font-size:9.5px;margin-right:3px}
.p-dr{color:#dc2626}
.p-cr{color:#16a34a}
.p-nil{color:#cbd5e1}
.p-suf{font-size:8px;margin-left:1px;font-weight:800;opacity:.7}
.p-foot{margin-top:20px;padding-top:10px;border-top:1px solid #e2e8f0;text-align:right;font-size:9px;color:#94a3b8}
@media print{thead{display:table-header-group}tr{page-break-inside:avoid}}
</style></head><body>
<div class="p-hdr">
  <div>
    <div class="p-rtype">${isBank?"Bank Book":"Cash Book"}</div>
    <div class="p-coname">${cbEsc(d.company)}</div>
  </div>
  <div class="p-hdr-right">Printed: ${cbEsc(printedDate)}</div>
</div>
<div class="p-info">
  <div>
    <div style="font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#94a3b8;margin-bottom:4px">Account</div>
    <div class="p-info-name">${cbEsc(d.account_name)}<span class="p-badge">${cbEsc(d.account_type)}</span></div>
  </div>
  <div style="text-align:right">
    <div class="p-period">${cbEsc(d.from_date)}  →  ${cbEsc(d.to_date)}</div>
    <div class="p-txncount">${d.row_count} transaction${d.row_count!==1?"s":""}</div>
  </div>
</div>
<table>
  <thead><tr>
    <th class="p-dt">Date</th>
    <th class="p-part">Particulars</th>
    <th class="p-vt">Vch Type</th>
    <th class="p-vno">Vch No</th>
    <th class="p-num r">Receipts (₹)</th>
    <th class="p-num r">Payments (₹)</th>
    <th class="p-num r">Balance (₹)</th>
  </tr></thead>
  <tbody>${tRows}</tbody>
</table>
<div class="p-foot">Powered by Dux DigiTech</div>
<script>window.onload=function(){window.print()}<\/script>
</body></html>`);
		win.document.close();
	}
}

/* ── Utilities ──────────────────────────────────────────────────── */
function _gel(id){ return document.getElementById(id); }
function cbEsc(str){
	if(str===null||str===undefined) return "";
	return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function cbFmt(val){
	return new Intl.NumberFormat("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2}).format(val||0);
}
function cbBal(val,type){
	if(!val) return '<span style="color:#9ca3af;font-family:monospace">0.00</span>';
	var cls=type==="Dr"?"cb-bal-dr":"cb-bal-cr";
	return `<span class="${cls}">${cbFmt(val)}<span class="cb-bsuf">${type}</span></span>`;
}
function cbPill(vtype){
	var m={"Payment Voucher":"cb-pill-pv","Receipt Voucher":"cb-pill-rv","Journal Entry":"cb-pill-jv","Contra Entry":"cb-pill-cv","Payment Entry":"cb-pill-pv","Receipt Entry":"cb-pill-rv","Purchase Invoice":"cb-pill-pi"};
	return `<span class="cb-pill ${m[vtype]||"cb-pill-other"}">${cbEsc(vtype)}</span>`;
}
