/* ============================================================
   dux_daybook.js  —  Tally-style Day Book
   Dux DigiTech  —  dux_voucher app
   ============================================================ */

frappe.pages["dux-daybook"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Day Book",
			single_column: true,
		});
		window._dux_daybook_instance = new DuxDayBook(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
		);
		console.error("dux-daybook:", e);
	}
};

frappe.pages["dux-daybook"].on_page_show = function (wrapper) {
	if (window._dux_daybook_instance && frappe.route_options) {
		window._dux_daybook_instance.applyRouteOptions(frappe.route_options);
		frappe.route_options = null;
	}
};

/* ============================================================
   DuxDayBook
   ============================================================ */
class DuxDayBook {
	constructor(wrapper, page) {
		this.wrapper   = wrapper;
		this.page      = page;
		this._lastData = null;
		this._companies = [];   // populated by _loadCompanies

		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();
	}

	_injectStyles() {
		if (document.getElementById("db-styles")) return;
		var s = document.createElement("style");
		s.id = "db-styles";
		s.textContent = `
.db-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.db-filter-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px 24px;margin-bottom:20px;display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px}
.db-fg{display:flex;flex-direction:column;gap:5px}
.db-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.db-fg select,.db-fg input[type=date],.db-fg input[type=text]{height:36px;border:1px solid #e5e7eb;border-radius:7px;padding:0 11px;font-size:13px;color:#111827;background:#fff;outline:none;transition:border .15s;font-family:inherit;box-sizing:border-box}
.db-fg select:focus,.db-fg input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.08)}
#db-co-inp{min-width:220px}
.db-fg-co{position:relative}
.db-drop{position:absolute;z-index:9999;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.12);min-width:240px;max-height:300px;overflow-y:auto;margin-top:3px;top:100%;left:0}
.db-drop-item{padding:9px 14px;cursor:pointer;border-bottom:1px solid #f9fafb;font-size:13px;color:#111827}
.db-drop-item:last-child{border-bottom:none}
.db-drop-item:hover{background:#f0f4ff}
.db-drop-empty{padding:16px;font-size:13px;color:#9ca3af;text-align:center}
.db-sel-pill{display:inline-flex;align-items:center;gap:5px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:5px;padding:2px 8px;font-size:12px;font-weight:500;color:#1d4ed8;margin-bottom:4px;cursor:pointer}
.db-sel-pill-x{font-size:14px;line-height:1;color:#93c5fd;margin-left:2px}
.db-sel-pill-x:hover{color:#1d4ed8}
#db-vt-sel{min-width:165px}
#db-from,#db-to{width:148px}
.db-btn-row{display:flex;gap:8px;align-items:flex-end}
.db-btn{height:36px;padding:0 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;font-family:inherit;transition:all .15s}
.db-btn-primary{background:#2563eb;border-color:#2563eb;color:#fff}
.db-btn-primary:hover{background:#1d4ed8}
.db-btn-secondary{background:#fff;color:#374151}
.db-btn-secondary:hover{background:#f9fafb}
.db-print-split{display:none;position:relative}
.db-print-split-inner{display:flex;border:1px solid #e5e7eb;border-radius:7px;overflow:hidden}
.db-print-main{height:36px;padding:0 14px;font-size:13px;font-weight:600;cursor:pointer;border:none;border-right:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:background .15s;display:flex;align-items:center;gap:6px}
.db-print-main:hover{background:#f9fafb}
.db-print-caret{height:36px;width:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;background:#fff;color:#9ca3af;font-family:inherit;transition:background .15s}
.db-print-caret:hover{background:#f3f4f6;color:#374151}
.db-print-menu{position:absolute;right:0;top:40px;background:#fff;border:1px solid #e5e7eb;border-radius:7px;box-shadow:0 8px 24px rgba(0,0,0,.1);min-width:170px;z-index:100;display:none}
.db-print-menu.open{display:block}
.db-print-opt{padding:10px 14px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:9px;color:#374151;border-bottom:1px solid #f3f4f6}
.db-print-opt:last-child{border-bottom:none}
.db-print-opt:hover{background:#f0f4ff;color:#1d4ed8}
.db-excel-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #16a34a;background:#16a34a;color:#fff;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.db-excel-btn:hover{background:#15803d;border-color:#15803d}
.db-placeholder{text-align:center;padding:64px 20px;color:#9ca3af;font-size:14px}
.db-placeholder strong{color:#6b7280}

/* Report card */
.db-report-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
.db-rpt-hdr{padding:18px 24px 14px;border-bottom:1px solid #f3f4f6}
.db-rpt-co{font-size:16px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.01em}
.db-rpt-sub{font-size:13px;color:#374151;margin-bottom:4px}
.db-rpt-period{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace;display:flex;align-items:center;gap:8px}
.db-rpt-period span{background:#f9fafb;border:1px solid #f3f4f6;border-radius:4px;padding:1px 7px}

/* Table */
.db-tbl-wrap{overflow-x:auto}
.db-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.db-tbl thead th{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;padding:9px 16px;background:#fafafa;border-bottom:1px solid #f3f4f6;white-space:nowrap;font-family:inherit}
.db-tbl thead th.r{text-align:right}
.db-tr-e td{padding:10px 16px;border-bottom:1px solid #f9fafb;vertical-align:top}
.db-tr-e:hover td{background:#fafbff}
.db-tr-r td{padding:1px 16px 9px 32px;border-bottom:1px solid #f9fafb;font-size:11px;color:#9ca3af;font-style:italic;line-height:1.5}
.db-tr-tot td{padding:10px 16px;border-top:2px solid #e5e7eb;font-size:12.5px;font-weight:700}
.db-tot-label{text-align:right;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;font-weight:700}

/* Cells */
.db-c-vt{width:130px;white-space:nowrap}
.db-c-vno{width:140px;white-space:nowrap}
.db-c-part{min-width:200px;font-size:13px;color:#111827;font-weight:500}
.db-c-amt{width:108px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-weight:500;color:#111827}
.db-deb{color:#dc2626}
.db-cred{color:#059669}
.db-nilamt{color:#d1d5db}
.db-c-date{width:80px;color:#9ca3af;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px}
.db-vno{color:#2563eb;text-decoration:none;font-size:12px;font-family:'SFMono-Regular',Consolas,monospace}
.db-vno:hover{text-decoration:underline}
.db-nil{color:#d1d5db}
.db-pill{display:inline-block;font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;letter-spacing:.03em;white-space:nowrap;font-family:inherit}
.db-pill-pv{background:#eff6ff;color:#1d4ed8}
.db-pill-rv{background:#f0fdf4;color:#166534}
.db-pill-jv{background:#fffbeb;color:#92400e}
.db-pill-cv{background:#f5f3ff;color:#5b21b6}
.db-pill-pi{background:#fff7ed;color:#c2410c}
.db-pill-si{background:#f0fdf4;color:#166534}
.db-pill-other{background:#f3f4f6;color:#4b5563;border:1px solid #e5e7eb}
/* Particulars wraps so long names never force horizontal scroll */
.db-c-part{word-break:break-word}
/* Responsive — shrink to fit narrow screens instead of overflowing */
@media(max-width:900px){
  .db-tbl{font-size:11.5px}
  .db-tbl thead th{padding:8px 9px}
  .db-tr-e td,.db-tr-tot td{padding:8px 9px}
  .db-c-date{width:60px;font-size:11px}
  .db-c-vt{width:94px}
  .db-c-vno{width:96px}
  .db-c-amt{width:84px}
  .db-c-part{min-width:120px}
  .db-tr-r td{padding-left:16px}
}
@media(max-width:600px){
  .db-tbl{font-size:11px}
  .db-tbl thead th,.db-tr-e td,.db-tr-tot td{padding:6px 6px}
  .db-c-vt{width:74px}
  .db-c-vno{width:82px}
  .db-c-amt{width:76px}
  .db-c-part{min-width:90px}
  .db-pill{font-size:9px;padding:2px 5px}
}
		`;
		document.head.appendChild(s);
	}

	_renderLayout() {
		$(this.wrapper).find(".layout-main-section").html(`
<div class="db-wrap">
  <div class="db-filter-card">
    <div class="db-fg db-fg-co">
      <label>Company</label>
      <div id="db-co-pill-wrap"></div>
      <input id="db-co-inp" type="text" placeholder="Type to search company…" autocomplete="off">
      <input id="db-co-sel" type="hidden">
      <div class="db-drop" id="db-co-drop" style="display:none"></div>
    </div>
    <div class="db-fg">
      <label>From</label>
      <input id="db-from" type="date">
    </div>
    <div class="db-fg">
      <label>To</label>
      <input id="db-to" type="date">
    </div>
    <div class="db-fg">
      <label>Voucher Type</label>
      <select id="db-vt-sel">
        <option value="All">All Vouchers</option>
        <option value="Payment Voucher">Payment Voucher</option>
        <option value="Receipt Voucher">Receipt Voucher</option>
        <option value="Contra Entry">Contra Entry</option>
        <option value="Journal Entry">Journal Entry</option>
        <option value="Purchase Invoice">Purchase Invoice</option>
        <option value="Sales Invoice">Sales Invoice</option>
      </select>
    </div>
    <div class="db-btn-row">
      <button class="db-btn db-btn-primary" id="db-show-btn">Show</button>
      <button class="db-excel-btn" id="db-excel-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M8 13l3 3-3 3M14 13l-3 3 3 3"/></svg>Excel
      </button>
      <div class="db-print-split" id="db-print-split">
        <div class="db-print-split-inner">
          <button class="db-print-main" id="db-print-p-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Print
          </button>
          <button class="db-print-caret" id="db-print-caret">
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div class="db-print-menu" id="db-print-menu">
          <div class="db-print-opt" id="db-opt-p">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Portrait (A4)
          </div>
          <div class="db-print-opt" id="db-opt-l">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>Landscape (A4)
          </div>
        </div>
      </div>
    </div>
  </div>
  <div id="db-area">
    <div class="db-placeholder">Select a company and date range, then click <strong>Show</strong>.</div>
  </div>
</div>`);
	}

	_bindEvents() {
		var self = this;
		_gel("db-co-inp").addEventListener("input", function(){ self._renderCompanyDropdown(this.value); });
		_gel("db-co-inp").addEventListener("focus", function(){ self._renderCompanyDropdown(this.value); });
		document.addEventListener("click", function(e){
			if(!e.target.closest(".db-fg-co"))      _gel("db-co-drop").style.display="none";
			if(!e.target.closest(".db-print-split")) _gel("db-print-menu").classList.remove("open");
		});
		_gel("db-show-btn").addEventListener("click", function(){ self.fetchReport(); });
		_gel("db-excel-btn").addEventListener("click", function(){ self._exportExcel(); });
		_gel("db-print-p-btn").addEventListener("click", function(){ _gel("db-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("db-print-caret").addEventListener("click", function(e){ e.stopPropagation(); _gel("db-print-menu").classList.toggle("open"); });
		_gel("db-opt-p").addEventListener("click",  function(){ _gel("db-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("db-opt-l").addEventListener("click",  function(){ _gel("db-print-menu").classList.remove("open"); self._printReport(true); });
		["db-co-inp","db-from","db-to","db-vt-sel"].forEach(function(id){
			_gel(id).addEventListener("keydown", function(ev){ if(ev.key==="Enter") self.fetchReport(); });
		});
	}

	_setDefaultDates() {
		var now=new Date();
		// Default: today only (Day Book is typically a single day)
		var today = now.toISOString().split("T")[0];
		_gel("db-from").value = today;
		_gel("db-to").value   = today;
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
		var self=this, drop=_gel("db-co-drop");
		var lc=(filterTxt||"").toLowerCase();
		var matched=this._companies.filter(function(c){ return c.toLowerCase().indexOf(lc)!==-1; });
		if(!matched.length){
			drop.innerHTML='<div class="db-drop-empty">No companies match</div>';
			drop.style.display="block";
			return;
		}
		drop.innerHTML=matched.map(function(c){
			return `<div class="db-drop-item db-co-item" data-v="${dbEsc(c)}">${dbEsc(c)}</div>`;
		}).join("");
		drop.style.display="block";
		drop.querySelectorAll(".db-co-item").forEach(function(el){
			el.addEventListener("click", function(){ self._selectCompany(el.dataset.v); });
		});
	}

	_selectCompany(name){
		var self=this;
		_gel("db-co-sel").value=name;
		_gel("db-co-inp").value="";
		_gel("db-co-inp").placeholder="Selected ↑ — type to change";
		_gel("db-co-drop").style.display="none";
		_gel("db-co-pill-wrap").innerHTML=
			`<div class="db-sel-pill">${dbEsc(name)}<span class="db-sel-pill-x" id="db-co-clear">×</span></div>`;
		_gel("db-co-clear").addEventListener("click", function(){ self._clearCompany(); });
	}

	_clearCompany(){
		_gel("db-co-sel").value="";
		_gel("db-co-inp").value="";
		_gel("db-co-inp").placeholder="Type to search company…";
		_gel("db-co-pill-wrap").innerHTML="";
		_gel("db-co-drop").style.display="none";
	}

	applyRouteOptions(opts){
		if(opts.company)   this._selectCompany(opts.company);
		if(opts.from_date) _gel("db-from").value=opts.from_date;
		if(opts.to_date)   _gel("db-to").value=opts.to_date;
		if(opts.company)   this.fetchReport();
	}

	fetchReport(){
		var company   = _gel("db-co-sel").value;
		var from_date = _gel("db-from").value;
		var to_date   = _gel("db-to").value;
		var vt_filter = _gel("db-vt-sel").value;

		if(!company)  { frappe.msgprint({message:"Please select a Company.",indicator:"orange"}); return; }
		if(!from_date||!to_date){ frappe.msgprint({message:"Please set both dates.",indicator:"orange"}); return; }

		_gel("db-area").innerHTML='<div class="db-placeholder">Loading…</div>';
		_gel("db-print-split").style.display="none";
		_gel("db-excel-btn").style.display="none";
		this._lastData=null;

		var self=this;
		frappe.call({
			method: "dux_voucher.dux_voucher.api.reports_api.get_day_book",
			args:{company, from_date, to_date, voucher_type_filter: vt_filter},
			callback: function(r){
				if(r.message){
					self._lastData=r.message;
					self._render(r.message);
					_gel("db-print-split").style.display="block";
					_gel("db-excel-btn").style.display="inline-flex";
				} else {
					_gel("db-area").innerHTML='<div class="db-placeholder">No transactions found for this period.</div>';
				}
			},
			error:function(){
				_gel("db-area").innerHTML='<div class="db-placeholder" style="color:#dc2626">Could not load Day Book. Try again.</div>';
			},
		});
	}

	_render(d){
		if(!d.rows.length){
			_gel("db-area").innerHTML='<div class="db-placeholder">No transactions found for this period.</div>';
			return;
		}

		var rows="";

		d.rows.forEach(function(row){
			rows+=`<tr class="db-tr-e">
				<td class="db-c-date">${dbEsc(row.posting_date)}</td>
				<td class="db-c-vt">${dbPill(row.voucher_type)}</td>
				<td class="db-c-vno"><a class="db-vno" href="${dbEsc(row.voucher_url)}" target="_blank">${dbEsc(row.voucher_no)}</a></td>
				<td class="db-c-part">${dbEsc(row.particulars)}</td>
				<td class="db-c-amt">${row.debit>0?`<span class="db-deb">${dbFmt(row.debit)}</span>`:'<span class="db-nilamt">—</span>'}</td>
				<td class="db-c-amt">${row.credit>0?`<span class="db-cred">${dbFmt(row.credit)}</span>`:'<span class="db-nilamt">—</span>'}</td>
			</tr>`;

			if(row.remarks){
				rows+=`<tr class="db-tr-r"><td colspan="6">${dbEsc(row.remarks)}</td></tr>`;
			}
		});

		// Totals row — Debit and Credit tie out for a balanced day book
		rows+=`<tr class="db-tr-tot">
			<td colspan="4" class="db-tot-label">Total — ${d.row_count} voucher${d.row_count!==1?"s":""}</td>
			<td class="db-c-amt db-deb">${dbFmt(d.total_debit)}</td>
			<td class="db-c-amt db-cred">${dbFmt(d.total_credit)}</td>
		</tr>`;

		_gel("db-area").innerHTML=`
<div class="db-report-card">
  <div class="db-rpt-hdr">
    <div class="db-rpt-co">${dbEsc(d.company)}</div>
    <div class="db-rpt-sub">Day Book</div>
    <div class="db-rpt-period">
      <span>${dbEsc(d.from_date)}</span><span style="color:#d1d5db">→</span><span>${dbEsc(d.to_date)}</span>
      <span style="color:#d1d5db">·</span><span>${d.row_count} voucher${d.row_count!==1?"s":""}</span>
    </div>
  </div>
  <div class="db-tbl-wrap">
    <table class="db-tbl">
      <thead><tr>
        <th class="db-c-date">Date</th>
        <th class="db-c-vt">Vch Type</th>
        <th class="db-c-vno">Vch No</th>
        <th class="db-c-part">Particulars</th>
        <th class="db-c-amt r">Debit</th>
        <th class="db-c-amt r">Credit</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
	}

	/* ── Excel Export ──────────────────────────────────────────────── */
	_exportExcel(){
		if(!this._lastData) return;
		var company=_gel("db-co-sel").value,
		    from_date=_gel("db-from").value,
		    to_date=_gel("db-to").value,
		    vt_filter=_gel("db-vt-sel").value;
		var params=new URLSearchParams({company:company,from_date:from_date,to_date:to_date});
		if(vt_filter) params.append("voucher_type_filter",vt_filter);
		var url="/api/method/dux_voucher.dux_voucher.api.reports_export.export_day_book_xlsx?"+params.toString();
		window.location.href=url;
	}

	/* ── Professional Print ────────────────────────────────────────── */
	_printReport(landscape){
		if(!this._lastData) return;
		var d   = this._lastData;
		var win = window.open("","_blank","width=1000,height=700");
		if(!win){ frappe.msgprint("Please allow pop-ups for this site."); return; }

		var pageRule = landscape
			? "@page{size:A4 landscape;margin:12mm 14mm 18mm}@page{@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);font-size:8.5px;color:#64748b;font-family:'Segoe UI',Arial,sans-serif}}"
			: "@page{size:A4 portrait;margin:16mm 12mm 18mm}@page{@bottom-right{content:'Page ' counter(page) ' of ' counter(pages);font-size:8.5px;color:#64748b;font-family:'Segoe UI',Arial,sans-serif}}";

		var printedDate = new Date().toLocaleDateString("en-IN",{day:"2-digit",month:"long",year:"numeric"});

		var tRows = "";

		d.rows.forEach(function(row, idx){
			tRows+=`<tr class="${idx%2===0?"p-even":"p-odd"}">
				<td class="p-dt">${dbEsc(row.posting_date)}</td>
				<td class="p-vt">${dbEsc(row.voucher_type)}</td>
				<td class="p-vno">${dbEsc(row.voucher_no)}</td>
				<td class="p-part">${dbEsc(row.particulars)}</td>
				<td class="p-amt">${row.debit>0?`<span class="p-deb">${dbFmt(row.debit)}</span>`:'<span class="p-nil">—</span>'}</td>
				<td class="p-amt">${row.credit>0?`<span class="p-cred">${dbFmt(row.credit)}</span>`:'<span class="p-nil">—</span>'}</td>
			</tr>`;

			if(row.remarks){
				tRows+=`<tr class="p-rmk"><td colspan="6">${dbEsc(row.remarks)}</td></tr>`;
			}
		});

		tRows+=`<tr class="p-tot">
			<td colspan="4" class="p-tot-lbl">Total — ${d.row_count} voucher${d.row_count!==1?"s":""}</td>
			<td class="p-amt p-deb p-fw">${dbFmt(d.total_debit)}</td>
			<td class="p-amt p-cred p-fw">${dbFmt(d.total_credit)}</td>
		</tr>`;

		win.document.write(`<!DOCTYPE html>
<html><head><meta charset="UTF-8">
<title>Day Book — ${dbEsc(d.company)}</title>
<style>
${pageRule}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;font-size:11px;background:#fff;color:#1e293b}
.p-hdr{display:flex;justify-content:space-between;align-items:flex-end;padding-bottom:10px;margin-bottom:14px;border-bottom:3px solid #0f172a}
.p-rtype{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.18em;color:#94a3b8;margin-bottom:5px}
.p-coname{font-size:21px;font-weight:800;color:#0f172a;letter-spacing:-.4px}
.p-hdr-right{text-align:right;font-size:9px;color:#94a3b8}
.p-info{display:flex;justify-content:space-between;align-items:center;background:#f8fafc;border:1px solid #e2e8f0;border-left:4.5px solid #7c3aed;border-radius:0 6px 6px 0;padding:10px 16px;margin-bottom:16px}
.p-period{font-size:10px;color:#475569;font-family:monospace}
.p-txncount{font-size:9px;color:#94a3b8;margin-top:2px}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
table{width:100%;border-collapse:collapse}
thead tr{background:#1e293b}
thead th{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#f1f5f9;padding:7px 9px;white-space:nowrap}
thead th.r{text-align:right}
.p-even td{background:#fff;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-odd  td{background:#fafbfc;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-rmk td{padding:0 9px 6px 20px;border-bottom:1px solid #f1f5f9;font-size:9px;color:#94a3b8;font-style:italic}
.p-tot td{border-top:2.5px solid #0f172a;padding:8px 9px;font-weight:800;background:#f8fafc}
.p-tot-lbl{text-align:right;font-size:8.5px;text-transform:uppercase;letter-spacing:.1em;color:#64748b}
.p-dt{width:58px;font-size:10px;color:#475569;font-family:monospace;white-space:nowrap}
.p-vt{width:90px;font-size:10px;color:#374151}
.p-vno{width:102px;font-family:monospace;font-size:10px;color:#1d4ed8}
.p-part{font-size:11px;color:#0f172a;font-weight:500;word-break:break-word}
.p-amt{width:82px;text-align:right;font-family:monospace;font-size:11px;color:#0f172a}
.p-deb{color:#dc2626}
.p-cred{color:#16a34a}
.p-nil{color:#cbd5e1}
.p-fw{font-weight:700}
.p-foot{margin-top:20px;padding-top:10px;border-top:1px solid #e2e8f0;text-align:right;font-size:9px;color:#94a3b8}
@media print{thead{display:table-header-group}tr{page-break-inside:avoid}}
</style></head><body>
<div class="p-hdr">
  <div><div class="p-rtype">Day Book</div><div class="p-coname">${dbEsc(d.company)}</div></div>
  <div class="p-hdr-right">Printed: ${dbEsc(printedDate)}</div>
</div>
<div class="p-info">
  <div><div class="p-period">${dbEsc(d.from_date)}  →  ${dbEsc(d.to_date)}</div><div class="p-txncount">${d.row_count} voucher${d.row_count!==1?"s":""}</div></div>
</div>
<table>
  <thead><tr>
    <th class="p-dt">Date</th>
    <th class="p-vt">Vch Type</th>
    <th class="p-vno">Vch No</th>
    <th class="p-part">Particulars</th>
    <th class="p-amt r">Debit</th>
    <th class="p-amt r">Credit</th>
  </tr></thead>
  <tbody>${tRows}</tbody>
</table>
<div class="p-foot">Powered by Dux DigiTech</div>
<script>window.onload=function(){window.print()}<\/script>
</body></html>`);
		win.document.close();
	}
}

/* ── Utilities (prefixed db to avoid global collision) ─────────── */
function _gel(id){ return document.getElementById(id); }
function dbEsc(str){
	if(str===null||str===undefined) return "";
	return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
function dbFmt(val){
	return new Intl.NumberFormat("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2}).format(val||0);
}
function dbPill(vtype){
	var m={"Payment Voucher":"db-pill-pv","Receipt Voucher":"db-pill-rv","Journal Entry":"db-pill-jv","Contra Entry":"db-pill-cv","Payment Entry":"db-pill-pv","Receipt Entry":"db-pill-rv","Purchase Invoice":"db-pill-pi","Sales Invoice":"db-pill-si"};
	return `<span class="db-pill ${m[vtype]||"db-pill-other"}">${dbEsc(vtype)}</span>`;
}
