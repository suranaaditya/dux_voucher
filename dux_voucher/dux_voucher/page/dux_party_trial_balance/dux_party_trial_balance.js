/* ============================================================
   dux_party_trial_balance.js  —  Party Trial Balance
   Dux DigiTech  —  dux_voucher app

   Trial balance for every party of one type (Customer / Supplier /
   Employee) in a company: opening, period debit/credit and closing per
   party. Clicking a party opens that exact party's ledger in the Party
   Ledger page (same company + same party).
   ============================================================ */

frappe.pages["dux-party-trial-balance"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Party Trial Balance",
			single_column: true,
		});
		window._dux_ptb_instance = new DuxPartyTrialBalance(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
		);
		console.error("dux-party-trial-balance:", e);
	}
};

frappe.pages["dux-party-trial-balance"].on_page_show = function (wrapper) {
	if (window._dux_ptb_instance && frappe.route_options) {
		window._dux_ptb_instance.applyRouteOptions(frappe.route_options);
		frappe.route_options = null;
	}
};

/* ============================================================ */
class DuxPartyTrialBalance {
	constructor(wrapper, page) {
		this.wrapper    = wrapper;
		this.page       = page;
		this._lastData  = null;
		this._companies = [];
		this._company   = "";
		this._partyType = "Customer";

		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();
	}

	_injectStyles() {
		if (document.getElementById("ptb-styles")) return;
		var s = document.createElement("style");
		s.id = "ptb-styles";
		s.textContent = `
.ptb-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.ptb-filter-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px 24px;margin-bottom:20px;display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px}
.ptb-fg{display:flex;flex-direction:column;gap:5px}
.ptb-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.ptb-fg select,.ptb-fg input[type=text],.ptb-fg input[type=date]{height:36px;border:1px solid #e5e7eb;border-radius:7px;padding:0 11px;font-size:13px;color:#111827;background:#fff;outline:none;transition:border .15s;font-family:inherit;box-sizing:border-box}
.ptb-fg select:focus,.ptb-fg input:focus{border-color:#2563eb;box-shadow:0 0 0 3px rgba(37,99,235,.08)}
#ptb-co-inp{min-width:220px}
#ptb-pt-sel{min-width:150px}
#ptb-from,#ptb-to{width:148px}
.ptb-fg-co{position:relative}
.ptb-drop{position:absolute;z-index:9999;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.12);min-width:240px;max-height:300px;overflow-y:auto;margin-top:3px;top:100%;left:0}
.ptb-drop-item{padding:9px 14px;cursor:pointer;border-bottom:1px solid #f9fafb;font-size:13px;color:#111827}
.ptb-drop-item:last-child{border-bottom:none}
.ptb-drop-item:hover{background:#f0f4ff}
.ptb-drop-empty{padding:16px;font-size:13px;color:#9ca3af;text-align:center}
.ptb-sel-pill{display:inline-flex;align-items:center;gap:5px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:5px;padding:2px 8px;font-size:12px;font-weight:500;color:#1d4ed8;margin-bottom:4px;cursor:pointer}
.ptb-sel-pill-x{font-size:14px;line-height:1;color:#93c5fd;margin-left:2px}
.ptb-sel-pill-x:hover{color:#1d4ed8}
.ptb-btn-row{display:flex;gap:8px;align-items:flex-end}
.ptb-btn{height:36px;padding:0 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;font-family:inherit;transition:all .15s}
.ptb-btn-primary{background:#2563eb;border-color:#2563eb;color:#fff}
.ptb-btn-primary:hover{background:#1d4ed8}
.ptb-excel-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #16a34a;background:#16a34a;color:#fff;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.ptb-excel-btn:hover{background:#15803d;border-color:#15803d}
.ptb-print-split{display:none;position:relative}
.ptb-print-split-inner{display:flex;border:1px solid #e5e7eb;border-radius:7px;overflow:hidden}
.ptb-print-main{height:36px;padding:0 14px;font-size:13px;font-weight:600;cursor:pointer;border:none;border-right:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:background .15s;display:flex;align-items:center;gap:6px}
.ptb-print-main:hover{background:#f9fafb}
.ptb-print-caret{height:36px;width:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;background:#fff;color:#9ca3af;font-family:inherit;transition:background .15s}
.ptb-print-caret:hover{background:#f3f4f6;color:#374151}
.ptb-print-menu{position:absolute;right:0;top:40px;background:#fff;border:1px solid #e5e7eb;border-radius:7px;box-shadow:0 8px 24px rgba(0,0,0,.1);min-width:170px;z-index:100;display:none}
.ptb-print-menu.open{display:block}
.ptb-print-opt{padding:10px 14px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:9px;color:#374151;border-bottom:1px solid #f3f4f6}
.ptb-print-opt:last-child{border-bottom:none}
.ptb-print-opt:hover{background:#f0f4ff;color:#1d4ed8}
.ptb-placeholder{text-align:center;padding:64px 20px;color:#9ca3af;font-size:14px}
.ptb-placeholder strong{color:#6b7280}
.ptb-report-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
.ptb-rpt-hdr{padding:18px 24px 14px;border-bottom:1px solid #f3f4f6}
.ptb-rpt-co{font-size:16px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.01em}
.ptb-rpt-sub{font-size:13px;color:#374151;margin-bottom:4px;display:flex;align-items:center;gap:8px}
.ptb-pt-badge{font-size:10px;font-weight:700;background:#f0fdf4;color:#166534;border-radius:4px;padding:2px 7px;letter-spacing:.03em}
.ptb-rpt-period{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace;display:flex;align-items:center;gap:8px}
.ptb-rpt-period span{background:#f9fafb;border:1px solid #f3f4f6;border-radius:4px;padding:1px 7px}
.ptb-tbl-wrap{overflow-x:auto}
.ptb-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.ptb-tbl thead th{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;padding:9px 16px;background:#fafafa;border-bottom:1px solid #f3f4f6;white-space:nowrap;font-family:inherit}
.ptb-tbl thead th.r{text-align:right}
.ptb-tr-e td{padding:10px 16px;border-bottom:1px solid #f9fafb;vertical-align:top}
.ptb-tr-e:hover td{background:#fafbff}
.ptb-tr-tot td{padding:10px 16px;border-top:2px solid #e5e7eb;font-size:12.5px;font-weight:700}
.ptb-tot-label{text-align:right;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;font-weight:700}
.ptb-c-party{width:160px;white-space:nowrap}
.ptb-c-name{min-width:180px;color:#111827;word-break:break-word}
.ptb-c-amt{width:120px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.ptb-party-link{color:#2563eb;text-decoration:none;font-weight:600;font-size:13px;cursor:pointer;font-family:'SFMono-Regular',Consolas,monospace}
.ptb-party-link:hover{text-decoration:underline}
.ptb-dr{color:#dc2626;font-weight:500}
.ptb-cr{color:#059669;font-weight:500}
.ptb-nil{color:#d1d5db}
.ptb-bal-dr{color:#dc2626;font-weight:700}
.ptb-bal-cr{color:#059669;font-weight:700}
.ptb-bsuf{font-size:9px;margin-left:2px;font-weight:700;opacity:.65;letter-spacing:.04em}
.ptb-tot-drcr{display:flex;flex-direction:column;line-height:1.35;font-size:11.5px}
@media(max-width:900px){
  .ptb-tbl{font-size:11.5px}
  .ptb-tbl thead th{padding:8px 9px}
  .ptb-tr-e td,.ptb-tr-tot td{padding:8px 9px}
  .ptb-c-party{width:120px}
  .ptb-c-name{min-width:110px}
  .ptb-c-amt{width:90px}
}
@media(max-width:600px){
  .ptb-tbl{font-size:11px}
  .ptb-tbl thead th,.ptb-tr-e td,.ptb-tr-tot td{padding:6px 6px}
  .ptb-c-party{width:96px}
  .ptb-c-name{min-width:80px}
  .ptb-c-amt{width:78px}
}
		`;
		document.head.appendChild(s);
	}

	_renderLayout() {
		$(this.wrapper).find(".layout-main-section").html(`
<div class="ptb-wrap">
  <div class="ptb-filter-card">
    <div class="ptb-fg ptb-fg-co">
      <label>Company</label>
      <div id="ptb-co-pill-wrap"></div>
      <input id="ptb-co-inp" type="text" placeholder="Type to search company…" autocomplete="off">
      <input id="ptb-co-sel" type="hidden">
      <div class="ptb-drop" id="ptb-co-drop" style="display:none"></div>
    </div>
    <div class="ptb-fg">
      <label>Party Type</label>
      <select id="ptb-pt-sel">
        <option value="Customer">Customer</option>
        <option value="Supplier">Supplier</option>
        <option value="Employee">Employee</option>
      </select>
    </div>
    <div class="ptb-fg"><label>From</label><input id="ptb-from" type="date"></div>
    <div class="ptb-fg"><label>To</label><input id="ptb-to" type="date"></div>
    <div class="ptb-btn-row">
      <button class="ptb-btn ptb-btn-primary" id="ptb-show-btn">Show</button>
      <button class="ptb-excel-btn" id="ptb-excel-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M8 13l3 3-3 3M14 13l-3 3 3 3"/></svg>Excel
      </button>
      <div class="ptb-print-split" id="ptb-print-split">
        <div class="ptb-print-split-inner">
          <button class="ptb-print-main" id="ptb-print-p-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Print
          </button>
          <button class="ptb-print-caret" id="ptb-print-caret">
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div class="ptb-print-menu" id="ptb-print-menu">
          <div class="ptb-print-opt" id="ptb-opt-p">Portrait (A4)</div>
          <div class="ptb-print-opt" id="ptb-opt-l">Landscape (A4)</div>
        </div>
      </div>
    </div>
  </div>
  <div id="ptb-area">
    <div class="ptb-placeholder">Select a company and party type, then click <strong>Show</strong>.</div>
  </div>
</div>`);
	}

	_bindEvents() {
		var self = this;
		_gel("ptb-co-inp").addEventListener("input", function(){ self._renderCompanyDropdown(this.value); });
		_gel("ptb-co-inp").addEventListener("focus", function(){ self._renderCompanyDropdown(this.value); });
		_gel("ptb-pt-sel").addEventListener("change", function(){ self._partyType = this.value; });
		document.addEventListener("click", function(e){
			if(!e.target.closest(".ptb-fg-co"))     _gel("ptb-co-drop").style.display="none";
			if(!e.target.closest(".ptb-print-split")) _gel("ptb-print-menu").classList.remove("open");
		});
		_gel("ptb-show-btn").addEventListener("click", function(){ self.fetchReport(); });
		_gel("ptb-excel-btn").addEventListener("click", function(){ self._exportExcel(); });
		_gel("ptb-print-p-btn").addEventListener("click", function(){ _gel("ptb-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("ptb-print-caret").addEventListener("click", function(e){ e.stopPropagation(); _gel("ptb-print-menu").classList.toggle("open"); });
		_gel("ptb-opt-p").addEventListener("click", function(){ _gel("ptb-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("ptb-opt-l").addEventListener("click", function(){ _gel("ptb-print-menu").classList.remove("open"); self._printReport(true); });
		["ptb-co-inp","ptb-from","ptb-to"].forEach(function(id){
			_gel(id).addEventListener("keydown", function(ev){ if(ev.key==="Enter") self.fetchReport(); });
		});
	}

	_setDefaultDates() {
		var now=new Date(), m=now.getMonth(), yr=now.getFullYear();
		var fy=m>=3?yr:yr-1;
		_gel("ptb-from").value=fy+"-04-01";
		_gel("ptb-to").value=now.toISOString().split("T")[0];
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
		var self=this, drop=_gel("ptb-co-drop");
		var lc=(filterTxt||"").toLowerCase();
		var matched=this._companies.filter(function(c){ return c.toLowerCase().indexOf(lc)!==-1; });
		if(!matched.length){ drop.innerHTML='<div class="ptb-drop-empty">No companies match</div>'; drop.style.display="block"; return; }
		drop.innerHTML=matched.map(function(c){ return `<div class="ptb-drop-item ptb-co-item" data-v="${_esc(c)}">${_esc(c)}</div>`; }).join("");
		drop.style.display="block";
		drop.querySelectorAll(".ptb-co-item").forEach(function(el){ el.addEventListener("click", function(){ self._selectCompany(el.dataset.v); }); });
	}

	_selectCompany(name){
		var self=this;
		this._company=name;
		_gel("ptb-co-sel").value=name;
		_gel("ptb-co-inp").value="";
		_gel("ptb-co-inp").placeholder="Selected ↑ — type to change";
		_gel("ptb-co-drop").style.display="none";
		_gel("ptb-co-pill-wrap").innerHTML=`<div class="ptb-sel-pill">${_esc(name)}<span class="ptb-sel-pill-x" id="ptb-co-clear">×</span></div>`;
		_gel("ptb-co-clear").addEventListener("click", function(){ self._clearCompany(); });
	}

	_clearCompany(){
		this._company="";
		_gel("ptb-co-sel").value="";
		_gel("ptb-co-inp").value="";
		_gel("ptb-co-inp").placeholder="Type to search company…";
		_gel("ptb-co-pill-wrap").innerHTML="";
		_gel("ptb-co-drop").style.display="none";
	}

	applyRouteOptions(opts){
		if(opts.company)   this._selectCompany(opts.company);
		if(opts.party_type){ this._partyType=opts.party_type; _gel("ptb-pt-sel").value=opts.party_type; }
		if(opts.from_date) _gel("ptb-from").value=opts.from_date;
		if(opts.to_date)   _gel("ptb-to").value=opts.to_date;
		if(opts.company)   this.fetchReport();
	}

	fetchReport(){
		var company=_gel("ptb-co-sel").value,
		    party_type=_gel("ptb-pt-sel").value,
		    from_date=_gel("ptb-from").value,
		    to_date=_gel("ptb-to").value;
		if(!company){ frappe.msgprint({message:"Please select a Company.",indicator:"orange"}); return; }
		if(!from_date||!to_date){ frappe.msgprint({message:"Please set both dates.",indicator:"orange"}); return; }
		this._company=company; this._partyType=party_type;
		_gel("ptb-area").innerHTML='<div class="ptb-placeholder">Loading…</div>';
		_gel("ptb-print-split").style.display="none";
		_gel("ptb-excel-btn").style.display="none";
		this._lastData=null;
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_party_trial_balance",
			args:{company,party_type,from_date,to_date},
			callback:function(r){
				if(r.message && r.message.rows.length){ self._lastData=r.message; self._render(r.message); _gel("ptb-print-split").style.display="block"; _gel("ptb-excel-btn").style.display="inline-flex"; }
				else{ _gel("ptb-area").innerHTML='<div class="ptb-placeholder">No '+_esc(party_type)+' balances found for this period.</div>'; }
			},
			error:function(){ _gel("ptb-area").innerHTML='<div class="ptb-placeholder" style="color:#dc2626">Could not load the trial balance. Try again.</div>'; },
		});
	}

	_render(d){
		var self=this, rows="";
		d.rows.forEach(function(row,i){
			var drHtml=row.debit>0?`<span class="ptb-dr">${_fmt(row.debit)}</span>`:`<span class="ptb-nil">—</span>`;
			var crHtml=row.credit>0?`<span class="ptb-cr">${_fmt(row.credit)}</span>`:`<span class="ptb-nil">—</span>`;
			rows+=`<tr class="ptb-tr-e">
				<td class="ptb-c-party"><a class="ptb-party-link" data-i="${i}" title="Open ledger">${_esc(row.party)}</a></td>
				<td class="ptb-c-name">${_esc(row.party_name)}</td>
				<td class="ptb-c-amt">${_bal(row.opening,row.opening_type)}</td>
				<td class="ptb-c-amt">${drHtml}</td>
				<td class="ptb-c-amt">${crHtml}</td>
				<td class="ptb-c-amt">${_bal(row.closing,row.closing_type)}</td>
			</tr>`;
		});
		rows+=`<tr class="ptb-tr-tot">
			<td colspan="2" class="ptb-tot-label">Total — ${d.row_count} part${d.row_count!==1?"ies":"y"}</td>
			<td class="ptb-c-amt">${_totDrCr(d.total_opening_debit,d.total_opening_credit)}</td>
			<td class="ptb-c-amt"><span class="ptb-dr">${_fmt(d.total_debit)}</span></td>
			<td class="ptb-c-amt"><span class="ptb-cr">${_fmt(d.total_credit)}</span></td>
			<td class="ptb-c-amt">${_totDrCr(d.total_closing_debit,d.total_closing_credit)}</td>
		</tr>`;

		_gel("ptb-area").innerHTML=`
<div class="ptb-report-card">
  <div class="ptb-rpt-hdr">
    <div class="ptb-rpt-co">${_esc(d.company)}</div>
    <div class="ptb-rpt-sub"><span>Party Trial Balance</span><span class="ptb-pt-badge">${_esc(d.party_type)}</span></div>
    <div class="ptb-rpt-period"><span>${_esc(d.from_date)}</span><span style="color:#d1d5db">→</span><span>${_esc(d.to_date)}</span><span style="color:#d1d5db">·</span><span>${d.row_count} part${d.row_count!==1?"ies":"y"}</span></div>
  </div>
  <div class="ptb-tbl-wrap">
    <table class="ptb-tbl">
      <thead><tr>
        <th class="ptb-c-party">Party</th><th class="ptb-c-name">Name</th>
        <th class="ptb-c-amt r">Opening</th><th class="ptb-c-amt r">Debit</th>
        <th class="ptb-c-amt r">Credit</th><th class="ptb-c-amt r">Closing</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;

		_gel("ptb-area").querySelectorAll(".ptb-party-link").forEach(function(el){
			el.addEventListener("click", function(){ self._openPartyLedger(self._lastData.rows[parseInt(el.dataset.i,10)]); });
		});
	}

	/* Deep-link: open the Party Ledger page for this exact party + company */
	_openPartyLedger(row){
		if(!row) return;
		frappe.route_options = {
			company:     this._company,
			party:       row.party,
			party_type:  this._partyType,
			account:     row.account || "",
			party_label: row.party_name || row.party,
			from_date:   _gel("ptb-from").value,
			to_date:     _gel("ptb-to").value,
		};
		frappe.set_route("dux-party-ledger");
	}

	_exportExcel(){
		if(!this._lastData) return;
		var params=new URLSearchParams({
			company:_gel("ptb-co-sel").value,
			party_type:_gel("ptb-pt-sel").value,
			from_date:_gel("ptb-from").value,
			to_date:_gel("ptb-to").value,
		});
		window.location.href="/api/method/dux_voucher.dux_voucher.api.reports_export.export_party_trial_balance_xlsx?"+params.toString();
	}

	_printReport(landscape){
		if(!this._lastData) return;
		var d=this._lastData;
		var win=window.open("","_blank","width=1100,height=750");
		if(!win){ frappe.msgprint("Please allow pop-ups for this site."); return; }
		var pageRule=landscape?"@page{size:A4 landscape;margin:12mm 14mm 14mm}":"@page{size:A4 portrait;margin:14mm 10mm 14mm}";
		var printedDate=new Date().toLocaleDateString("en-IN",{day:"2-digit",month:"long",year:"numeric"});

		var tRows="";
		d.rows.forEach(function(row,idx){
			var drH=row.debit>0?`<span class="p-dr">${_fmt(row.debit)}</span>`:'<span class="p-nil">—</span>';
			var crH=row.credit>0?`<span class="p-cr">${_fmt(row.credit)}</span>`:'<span class="p-nil">—</span>';
			tRows+=`<tr class="${idx%2===0?"p-even":"p-odd"}">
				<td class="p-party">${_esc(row.party)}</td>
				<td class="p-name">${_esc(row.party_name)}</td>
				<td class="p-num p-fw ${row.opening_type==="Dr"?"p-dr":"p-cr"}">${_fmt(row.opening)}<span class="p-suf">${row.opening_type}</span></td>
				<td class="p-num">${drH}</td>
				<td class="p-num">${crH}</td>
				<td class="p-num p-fw ${row.closing_type==="Dr"?"p-dr":"p-cr"}">${_fmt(row.closing)}<span class="p-suf">${row.closing_type}</span></td>
			</tr>`;
		});
		tRows+=`<tr class="p-tot">
			<td colspan="2" class="p-tot-lbl">Total — ${d.row_count} part${d.row_count!==1?"ies":"y"}</td>
			<td class="p-num">${_printDrCr(d.total_opening_debit,d.total_opening_credit)}</td>
			<td class="p-num p-dr p-fw">${_fmt(d.total_debit)}</td>
			<td class="p-num p-cr p-fw">${_fmt(d.total_credit)}</td>
			<td class="p-num">${_printDrCr(d.total_closing_debit,d.total_closing_credit)}</td>
		</tr>`;

		win.document.write(`<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>Party Trial Balance — ${_esc(d.company)}</title>
<style>
${pageRule}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',Arial,sans-serif;font-size:11px;background:#fff;color:#1e293b}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
.p-hdr{display:flex;justify-content:space-between;align-items:flex-end;padding-bottom:10px;margin-bottom:14px;border-bottom:3px solid #0f172a}
.p-rtype{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.18em;color:#94a3b8;margin-bottom:5px}
.p-coname{font-size:21px;font-weight:800;color:#0f172a;letter-spacing:-.4px}
.p-hdr-right{text-align:right;font-size:9px;color:#94a3b8}
.p-info{display:flex;justify-content:space-between;align-items:center;background:#f8fafc;border:1px solid #e2e8f0;border-left:4.5px solid #16a34a;border-radius:0 6px 6px 0;padding:10px 16px;margin-bottom:16px}
.p-info-name{font-size:13px;font-weight:800;color:#0f172a}
.p-period{font-size:10px;color:#475569;font-family:monospace}
table{width:100%;border-collapse:collapse}
thead tr{background:#1e293b}
thead th{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#f1f5f9;padding:7px 9px;white-space:nowrap}
thead th.r{text-align:right}
.p-even td{background:#fff;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-odd td{background:#fafbfc;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-tot td{border-top:2.5px solid #0f172a;padding:8px 9px;font-weight:800;background:#f8fafc}
.p-tot-lbl{text-align:right;font-size:8.5px;text-transform:uppercase;letter-spacing:.1em;color:#64748b}
.p-party{width:130px;font-family:monospace;font-size:10px;color:#1d4ed8;font-weight:700;word-break:break-word}
.p-name{font-size:10.5px;color:#0f172a;word-break:break-word}
.p-num{width:90px;text-align:right;font-family:monospace;font-size:10.5px;white-space:nowrap}
.p-fw{font-weight:700}
.p-dr{color:#dc2626}
.p-cr{color:#16a34a}
.p-nil{color:#cbd5e1}
.p-suf{font-size:8px;margin-left:1px;font-weight:800;opacity:.7}
.p-drcr{display:flex;flex-direction:column;line-height:1.3}
.p-foot{margin-top:20px;padding-top:10px;border-top:1px solid #e2e8f0;text-align:right;font-size:9px;color:#94a3b8}
@media print{thead{display:table-header-group}tr{page-break-inside:avoid}}
</style></head><body>
<div class="p-hdr"><div><div class="p-rtype">Party Trial Balance · ${_esc(d.party_type)}</div><div class="p-coname">${_esc(d.company)}</div></div><div class="p-hdr-right">Printed: ${_esc(printedDate)}</div></div>
<div class="p-info"><div><div class="p-info-name">${d.row_count} part${d.row_count!==1?"ies":"y"}</div></div><div class="p-period">${_esc(d.from_date)}  →  ${_esc(d.to_date)}</div></div>
<table>
  <thead><tr>
    <th class="p-party">Party</th><th class="p-name">Name</th>
    <th class="p-num r">Opening</th><th class="p-num r">Debit</th>
    <th class="p-num r">Credit</th><th class="p-num r">Closing</th>
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
function _fmt(val){ return new Intl.NumberFormat("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2}).format(val||0); }
function _esc(str){ if(str===null||str===undefined) return ""; return String(str).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
function _bal(val,type){
	if(!val) return '<span style="color:#9ca3af;font-family:monospace">0.00</span>';
	var cls=type==="Dr"?"ptb-bal-dr":"ptb-bal-cr";
	return `<span class="${cls}">${_fmt(val)}<span class="ptb-bsuf">${type}</span></span>`;
}
function _totDrCr(dr,cr){
	var parts=[];
	if(dr>0) parts.push(`<span class="ptb-bal-dr">${_fmt(dr)}<span class="ptb-bsuf">Dr</span></span>`);
	if(cr>0) parts.push(`<span class="ptb-bal-cr">${_fmt(cr)}<span class="ptb-bsuf">Cr</span></span>`);
	if(!parts.length) return '<span style="color:#9ca3af;font-family:monospace">0.00</span>';
	return `<span class="ptb-tot-drcr">${parts.join("")}</span>`;
}
function _printDrCr(dr,cr){
	var parts=[];
	if(dr>0) parts.push(`<span class="p-dr p-fw">${_fmt(dr)}<span class="p-suf">Dr</span></span>`);
	if(cr>0) parts.push(`<span class="p-cr p-fw">${_fmt(cr)}<span class="p-suf">Cr</span></span>`);
	if(!parts.length) return "0.00";
	return `<span class="p-drcr">${parts.join("")}</span>`;
}
