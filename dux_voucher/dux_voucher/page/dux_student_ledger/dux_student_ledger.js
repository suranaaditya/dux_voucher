/* ============================================================
   dux_student_ledger.js  —  Tally-style Student Ledger
   Dux DigiTech  —  dux_voucher app

   One unified Dr/Cr ledger statement for a single student, picked
   from either the Ex Student or the New Student (admission) module
   within a chosen company. Data comes from
   dux_voucher.dux_voucher.api.reports_api.get_student_ledger (NOT
   from GL Entry — see that function's docstring).

   Everything is wrapped in an IIFE so the local helpers (_gel, _fmt,
   _esc, _bal, _debounce) don't collide with the identically-named
   globals in dux_ledger.js when both pages are open in one session.
   ============================================================ */

(function () {

frappe.pages["dux-student-ledger"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "Student Ledger",
			single_column: true,
		});
		window._dux_student_ledger_instance = new DuxStudentLedger(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
		);
		console.error("dux-student-ledger:", e);
	}
};

frappe.pages["dux-student-ledger"].on_page_show = function (wrapper) {
	if (window._dux_student_ledger_instance && frappe.route_options) {
		window._dux_student_ledger_instance.applyRouteOptions(frappe.route_options);
		frappe.route_options = null;
	}
};

/* ============================================================
   DuxStudentLedger
   ============================================================ */
class DuxStudentLedger {
	constructor(wrapper, page) {
		this.wrapper    = wrapper;
		this.page       = page;
		this._kind      = "ex";   // default toggle — Ex Student
		this._student   = null;   // {value, label}
		this._lastData  = null;
		this._companies = [];

		this._injectStyles();
		this._renderLayout();
		this._bindEvents();
		this._setDefaultDates();
		this._loadCompanies();
	}

	_injectStyles() {
		if (document.getElementById("sl-styles")) return;
		var s = document.createElement("style");
		s.id = "sl-styles";
		s.textContent = `
.sl-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif}
.sl-filter-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:20px 24px;margin-bottom:20px;display:flex;flex-wrap:wrap;align-items:flex-end;gap:16px}
.sl-fg{display:flex;flex-direction:column;gap:5px}
.sl-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.sl-fg select,.sl-fg input[type=text],.sl-fg input[type=date]{height:36px;border:1px solid #e5e7eb;border-radius:7px;padding:0 11px;font-size:13px;color:#111827;background:#fff;outline:none;transition:border .15s;font-family:inherit;box-sizing:border-box}
.sl-fg select:focus,.sl-fg input:focus{border-color:#0d9488;box-shadow:0 0 0 3px rgba(13,148,136,.08)}
#sl-co-inp{min-width:220px}
#sl-stu-inp{min-width:280px}
#sl-from,#sl-to{width:148px}
.sl-fg-co{position:relative}
.sl-drop{position:absolute;z-index:9999;background:#fff;border:1px solid #e5e7eb;border-radius:8px;box-shadow:0 8px 28px rgba(0,0,0,.12);min-width:340px;max-height:320px;overflow-y:auto;margin-top:3px;top:100%;left:0}
#sl-co-drop{min-width:240px}
.sl-drop-section{padding:6px 12px 3px;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;border-bottom:1px solid #f3f4f6;background:#fafafa}
.sl-drop-item{padding:9px 14px;cursor:pointer;display:flex;flex-direction:column;gap:2px;border-bottom:1px solid #f9fafb}
.sl-drop-item:last-child{border-bottom:none}
.sl-drop-item:hover{background:#f0fdfa}
.sl-drop-label{font-size:13px;font-weight:500;color:#111827}
.sl-drop-meta{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace}
.sl-drop-empty{padding:16px;font-size:13px;color:#9ca3af;text-align:center}
.sl-fg-stu{position:relative}
.sl-sel-pill{display:inline-flex;align-items:center;gap:5px;background:#f0fdfa;border:1px solid #99f6e4;border-radius:5px;padding:2px 8px;font-size:12px;font-weight:500;color:#0f766e;margin-bottom:4px;cursor:pointer}
.sl-sel-pill-x{font-size:14px;line-height:1;color:#5eead4;margin-left:2px}
.sl-sel-pill-x:hover{color:#0f766e}
/* ── Student-type toggle ── */
.sl-toggle{display:inline-flex;border:1px solid #e5e7eb;border-radius:7px;overflow:hidden;height:36px}
.sl-toggle-btn{height:36px;padding:0 16px;font-size:13px;font-weight:600;cursor:pointer;border:none;background:#fff;color:#6b7280;font-family:inherit;transition:all .15s}
.sl-toggle-btn+.sl-toggle-btn{border-left:1px solid #e5e7eb}
.sl-toggle-btn:hover{background:#f9fafb}
.sl-toggle-btn.sl-active{background:#0d9488;color:#fff}
.sl-toggle-btn.sl-active:hover{background:#0f766e}
.sl-btn-row{display:flex;gap:8px;align-items:flex-end}
.sl-btn{height:36px;padding:0 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;font-family:inherit;transition:all .15s}
.sl-btn-primary{background:#0d9488;border-color:#0d9488;color:#fff}
.sl-btn-primary:hover{background:#0f766e}
.sl-print-split{display:none;position:relative}
.sl-print-split-inner{display:flex;border:1px solid #e5e7eb;border-radius:7px;overflow:hidden}
.sl-print-main{height:36px;padding:0 14px;font-size:13px;font-weight:600;cursor:pointer;border:none;border-right:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:background .15s;display:flex;align-items:center;gap:6px}
.sl-print-main:hover{background:#f9fafb}
.sl-print-caret{height:36px;width:32px;display:flex;align-items:center;justify-content:center;cursor:pointer;border:none;background:#fff;color:#9ca3af;font-family:inherit;transition:background .15s}
.sl-print-caret:hover{background:#f3f4f6;color:#374151}
.sl-print-menu{position:absolute;right:0;top:40px;background:#fff;border:1px solid #e5e7eb;border-radius:7px;box-shadow:0 8px 24px rgba(0,0,0,.1);min-width:170px;z-index:100;display:none}
.sl-print-menu.open{display:block}
.sl-print-opt{padding:10px 14px;font-size:13px;cursor:pointer;display:flex;align-items:center;gap:9px;color:#374151;border-bottom:1px solid #f3f4f6}
.sl-print-opt:last-child{border-bottom:none}
.sl-print-opt:hover{background:#f0fdfa;color:#0f766e}
.sl-excel-btn{display:none;height:36px;padding:0 14px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #16a34a;background:#16a34a;color:#fff;font-family:inherit;transition:all .15s;align-items:center;gap:6px}
.sl-excel-btn:hover{background:#15803d;border-color:#15803d}
.sl-placeholder{text-align:center;padding:64px 20px;color:#9ca3af;font-size:14px}
.sl-placeholder strong{color:#6b7280}
.sl-report-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;overflow:hidden}
.sl-rpt-hdr{padding:18px 24px 14px;border-bottom:1px solid #f3f4f6}
.sl-rpt-co{font-size:16px;font-weight:700;color:#111827;margin-bottom:3px;letter-spacing:-.01em}
.sl-rpt-ledger-row{display:flex;align-items:center;gap:8px;font-size:13px;color:#374151;margin-bottom:4px}
.sl-rpt-ledger-row strong{font-weight:600}
.sl-kind-badge{font-size:10px;font-weight:700;background:#f0fdfa;color:#0f766e;border-radius:4px;padding:2px 7px;letter-spacing:.03em}
.sl-rpt-period{font-size:11px;color:#9ca3af;font-family:'SFMono-Regular',Consolas,monospace;display:flex;align-items:center;gap:8px;margin-bottom:6px}
.sl-rpt-period span{background:#f9fafb;border:1px solid #f3f4f6;border-radius:4px;padding:1px 7px}
.sl-legend{font-size:11px;color:#9ca3af}
.sl-legend b{font-weight:700}
.sl-legend .sl-lg-dr{color:#dc2626}
.sl-legend .sl-lg-cr{color:#059669}
.sl-tbl-wrap{overflow-x:auto}
.sl-tbl{width:100%;border-collapse:collapse;font-size:12.5px}
.sl-tbl thead th{font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:#9ca3af;padding:9px 16px;background:#fafafa;border-bottom:1px solid #f3f4f6;white-space:nowrap;font-family:inherit}
.sl-tbl thead th.r{text-align:right}
.sl-tr-ob td,.sl-tr-cb td{padding:10px 16px;background:#f9fafb;font-size:12px}
.sl-tr-ob td{border-bottom:1px solid #f3f4f6}
.sl-tr-cb td{border-top:2px solid #e5e7eb}
.sl-ob-label,.sl-cb-label{font-weight:700;color:#374151;text-transform:uppercase;font-size:10px;letter-spacing:.08em}
.sl-tr-e td{padding:10px 16px;border-bottom:1px solid #f9fafb;vertical-align:top}
.sl-tr-e:hover td{background:#f6fefb}
.sl-tr-r td{padding:1px 16px 9px 32px;border-bottom:1px solid #f9fafb;font-size:11px;color:#9ca3af;font-style:italic;line-height:1.5;overflow-wrap:anywhere;word-break:break-word}
.sl-tr-tot td{padding:10px 16px;border-top:2px solid #e5e7eb;font-size:12.5px;font-weight:700}
.sl-tot-label{text-align:right;font-size:10px;color:#9ca3af;text-transform:uppercase;letter-spacing:.08em;font-weight:700}
.sl-c-date{width:80px;color:#9ca3af;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace;font-size:12px}
.sl-c-part{min-width:180px}
.sl-c-vt{width:130px;white-space:nowrap}
.sl-c-vno{width:140px;white-space:nowrap}
.sl-c-amt{width:110px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.sl-c-bal{width:120px;text-align:right;white-space:nowrap;font-family:'SFMono-Regular',Consolas,monospace}
.sl-contra-name{color:#111827;font-weight:500;font-size:13px}
.sl-vno{color:#0d9488;text-decoration:none;font-size:12px;font-family:'SFMono-Regular',Consolas,monospace}
.sl-vno:hover{text-decoration:underline}
.sl-dr{color:#dc2626;font-weight:500}
.sl-cr{color:#059669;font-weight:500}
.sl-nil{color:#d1d5db}
.sl-bal-dr{color:#dc2626;font-weight:700}
.sl-bal-cr{color:#059669;font-weight:700}
.sl-bsuf{font-size:9px;margin-left:2px;font-weight:700;opacity:.65;letter-spacing:.04em}
.sl-pill{display:inline-block;font-size:10px;font-weight:700;padding:3px 8px;border-radius:5px;letter-spacing:.03em;white-space:nowrap;font-family:inherit}
.sl-pill-receipt{background:#f0fdf4;color:#166534}
.sl-pill-refund{background:#fff7ed;color:#c2410c}
.sl-pill-opening{background:#eff6ff;color:#1d4ed8}
.sl-pill-writeoff{background:#f5f3ff;color:#5b21b6}
.sl-pill-other{background:#f3f4f6;color:#4b5563;border:1px solid #e5e7eb}
.sl-c-part,.sl-contra-name{word-break:break-word}
@media(max-width:900px){
  .sl-tbl{font-size:11.5px}
  .sl-tbl thead th{padding:8px 9px}
  .sl-tr-e td,.sl-tr-ob td,.sl-tr-cb td,.sl-tr-tot td{padding:8px 9px}
  .sl-c-date{width:58px;font-size:11px}
  .sl-c-vt{width:96px}
  .sl-c-vno{width:96px}
  .sl-c-amt{width:84px}
  .sl-c-bal{width:92px}
  .sl-c-part{min-width:110px}
  .sl-tr-r td{padding-left:16px}
}
@media(max-width:600px){
  .sl-tbl{font-size:11px}
  .sl-tbl thead th,.sl-tr-e td,.sl-tr-ob td,.sl-tr-cb td,.sl-tr-tot td{padding:6px 6px}
  .sl-c-vt{width:76px}
  .sl-c-vno{width:84px}
  .sl-c-amt{width:76px}
  .sl-c-bal{width:84px}
  .sl-c-part{min-width:80px}
  .sl-pill{font-size:9px;padding:2px 5px}
}
		`;
		document.head.appendChild(s);
	}

	_renderLayout() {
		$(this.wrapper).find(".layout-main-section").html(`
<div class="sl-wrap">
  <div class="sl-filter-card">
    <div class="sl-fg sl-fg-co">
      <label>Company</label>
      <div id="sl-co-pill-wrap"></div>
      <input id="sl-co-inp" type="text" placeholder="Type to search company…" autocomplete="off">
      <input id="sl-co-sel" type="hidden">
      <div class="sl-drop" id="sl-co-drop" style="display:none"></div>
    </div>
    <div class="sl-fg">
      <label>Student Type</label>
      <div class="sl-toggle">
        <button type="button" class="sl-toggle-btn sl-active" data-kind="ex"  id="sl-kind-ex">Ex Student</button>
        <button type="button" class="sl-toggle-btn"          data-kind="new" id="sl-kind-new">New Student</button>
      </div>
    </div>
    <div class="sl-fg sl-fg-stu">
      <label>Student</label>
      <div id="sl-stu-pill-wrap"></div>
      <input id="sl-stu-inp" type="text" placeholder="Select a company first…" autocomplete="off" disabled>
      <div class="sl-drop" id="sl-stu-drop" style="display:none"></div>
    </div>
    <div class="sl-fg"><label>From</label><input id="sl-from" type="date"></div>
    <div class="sl-fg"><label>To</label><input id="sl-to" type="date"></div>
    <div class="sl-btn-row">
      <button class="sl-btn sl-btn-primary" id="sl-show-btn">Show</button>
      <button class="sl-excel-btn" id="sl-excel-btn">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3v4a1 1 0 0 0 1 1h4"/><path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z"/><path d="M8 13l3 3-3 3M14 13l-3 3 3 3"/></svg>Excel
      </button>
      <div class="sl-print-split" id="sl-print-split">
        <div class="sl-print-split-inner">
          <button class="sl-print-main" id="sl-print-p-btn">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Print
          </button>
          <button class="sl-print-caret" id="sl-print-caret">
            <svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><polyline points="6 9 12 15 18 9"/></svg>
          </button>
        </div>
        <div class="sl-print-menu" id="sl-print-menu">
          <div class="sl-print-opt" id="sl-opt-p">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="6" y="2" width="12" height="20" rx="2"/></svg>Portrait (A4)
          </div>
          <div class="sl-print-opt" id="sl-opt-l">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="2" y="6" width="20" height="12" rx="2"/></svg>Landscape (A4)
          </div>
        </div>
      </div>
    </div>
  </div>
  <div id="sl-area">
    <div class="sl-placeholder">Select a company, choose <strong>Ex Student</strong> or <strong>New Student</strong>, pick a student, then click <strong>Show</strong>.</div>
  </div>
</div>`);
	}

	_bindEvents() {
		var self = this;
		// Company picker — type-to-filter.
		_gel("sl-co-inp").addEventListener("input", function(){ self._renderCompanyDropdown(this.value); });
		_gel("sl-co-inp").addEventListener("focus", function(){ self._renderCompanyDropdown(this.value); });

		// Student-type toggle.
		_gel("sl-kind-ex").addEventListener("click",  function(){ self._setKind("ex"); });
		_gel("sl-kind-new").addEventListener("click", function(){ self._setKind("new"); });

		// Student picker — search-as-you-type, also lists on focus.
		_gel("sl-stu-inp").addEventListener("input", _debounce(function(){
			var co=_gel("sl-co-sel").value;
			if(co) self._searchStudents(co, this.value.trim());
		}, 260));
		_gel("sl-stu-inp").addEventListener("focus", function(){
			var co=_gel("sl-co-sel").value;
			if(co) self._searchStudents(co, this.value.trim());
		});

		document.addEventListener("click", function(e){
			if(!e.target.closest(".sl-fg-co"))  _gel("sl-co-drop").style.display="none";
			if(!e.target.closest(".sl-fg-stu")) _gel("sl-stu-drop").style.display="none";
			if(!e.target.closest(".sl-print-split")) _gel("sl-print-menu").classList.remove("open");
		});
		_gel("sl-show-btn").addEventListener("click", function(){ self.fetchReport(); });
		_gel("sl-excel-btn").addEventListener("click", function(){ self._exportExcel(); });
		_gel("sl-print-p-btn").addEventListener("click", function(){ _gel("sl-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("sl-print-caret").addEventListener("click", function(e){ e.stopPropagation(); _gel("sl-print-menu").classList.toggle("open"); });
		_gel("sl-opt-p").addEventListener("click", function(){ _gel("sl-print-menu").classList.remove("open"); self._printReport(false); });
		_gel("sl-opt-l").addEventListener("click", function(){ _gel("sl-print-menu").classList.remove("open"); self._printReport(true); });
		["sl-co-inp","sl-stu-inp","sl-from","sl-to"].forEach(function(id){
			_gel(id).addEventListener("keydown", function(ev){ if(ev.key==="Enter") self.fetchReport(); });
		});
	}

	_setDefaultDates() {
		var now=new Date(), m=now.getMonth(), yr=now.getFullYear();
		var fy=m>=3?yr:yr-1;
		_gel("sl-from").value=fy+"-04-01";
		_gel("sl-to").value=now.toISOString().split("T")[0];
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
		var self=this, drop=_gel("sl-co-drop");
		var lc=(filterTxt||"").toLowerCase();
		var matched=this._companies.filter(function(c){ return c.toLowerCase().indexOf(lc)!==-1; });
		if(!matched.length){
			drop.innerHTML='<div class="sl-drop-empty">No companies match</div>';
			drop.style.display="block";
			return;
		}
		drop.innerHTML=matched.map(function(c){
			return `<div class="sl-drop-item sl-co-item" data-v="${_esc(c)}"><span class="sl-drop-label">${_esc(c)}</span></div>`;
		}).join("");
		drop.style.display="block";
		drop.querySelectorAll(".sl-co-item").forEach(function(el){
			el.addEventListener("click", function(){ self._selectCompany(el.dataset.v); });
		});
	}

	_selectCompany(name){
		var self=this;
		_gel("sl-co-sel").value=name;
		_gel("sl-co-inp").value="";
		_gel("sl-co-inp").placeholder="Selected ↑ — type to change";
		_gel("sl-co-drop").style.display="none";
		_gel("sl-co-pill-wrap").innerHTML=
			`<div class="sl-sel-pill">${_esc(name)}<span class="sl-sel-pill-x" id="sl-co-clear">×</span></div>`;
		_gel("sl-co-clear").addEventListener("click", function(){ self._clearCompany(); });
		// Student is company-scoped — wipe it and unlock the picker.
		this._clearStudent();
		this._enableStudentPicker();
	}

	_clearCompany(){
		_gel("sl-co-sel").value="";
		_gel("sl-co-inp").value="";
		_gel("sl-co-inp").placeholder="Type to search company…";
		_gel("sl-co-pill-wrap").innerHTML="";
		_gel("sl-co-drop").style.display="none";
		this._clearStudent();
		var inp=_gel("sl-stu-inp");
		inp.disabled=true; inp.placeholder="Select a company first…";
	}

	_setKind(kind){
		if(this._kind===kind) return;
		this._kind=kind;
		_gel("sl-kind-ex").classList.toggle("sl-active", kind==="ex");
		_gel("sl-kind-new").classList.toggle("sl-active", kind==="new");
		// Student list differs by kind — clear the current pick.
		this._clearStudent();
		_gel("sl-stu-drop").style.display="none";
	}

	_enableStudentPicker(){
		var inp=_gel("sl-stu-inp");
		inp.disabled=false;
		inp.placeholder="Type to search students…";
	}

	_clearStudent(){
		this._student=null;
		_gel("sl-stu-inp").value="";
		_gel("sl-stu-pill-wrap").innerHTML="";
		_gel("sl-stu-drop").style.display="none";
	}

	_searchStudents(company, txt){
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.search_students",
			args:{company:company, kind:this._kind, search_txt:txt},
			callback:function(r){
				var results=r.message||[], drop=_gel("sl-stu-drop");
				if(!results.length){ drop.innerHTML='<div class="sl-drop-empty">No students found</div>'; drop.style.display="block"; return; }
				var kindLabel=self._kind==="ex"?"Ex Students":"New Students";
				var html='<div class="sl-drop-section">'+kindLabel+'</div>'+results.map(function(i){
					return `<div class="sl-drop-item" data-v='${JSON.stringify(i).replace(/'/g,"&#39;")}'><span class="sl-drop-label">${_esc(i.label)}</span><span class="sl-drop-meta">${_esc(i.meta)}</span></div>`;
				}).join("");
				drop.innerHTML=html; drop.style.display="block";
				drop.querySelectorAll(".sl-drop-item").forEach(function(el){
					el.addEventListener("click", function(){ var item=JSON.parse(el.dataset.v); self._selectStudent(item); self.fetchReport(); });
				});
			},
		});
	}

	_selectStudent(item){
		var self=this;
		this._student=item;
		_gel("sl-stu-inp").value="";
		_gel("sl-stu-inp").placeholder="Selected ↑ — type to change";
		_gel("sl-stu-drop").style.display="none";
		_gel("sl-stu-pill-wrap").innerHTML=
			`<div class="sl-sel-pill">${_esc(item.label)}<span class="sl-sel-pill-x" id="sl-stu-clear">×</span></div>`;
		document.getElementById("sl-stu-clear").addEventListener("click", function(){ self._clearStudent(); self._enableStudentPicker(); });
	}

	applyRouteOptions(opts){
		if(opts.company)   this._selectCompany(opts.company);
		if(opts.kind)      this._setKind(opts.kind);
		if(opts.from_date) _gel("sl-from").value=opts.from_date;
		if(opts.to_date)   _gel("sl-to").value=opts.to_date;
		if(opts.company && opts.student){
			this._selectStudent({value:opts.student, label:opts.student, meta:""});
			this.fetchReport();
		}
	}

	fetchReport(){
		var company=_gel("sl-co-sel").value,
		    from_date=_gel("sl-from").value,
		    to_date=_gel("sl-to").value;
		var student=this._student?this._student.value:"";
		if(!company){ frappe.msgprint({message:"Please select a Company.",indicator:"orange"}); return; }
		if(!student){ frappe.msgprint({message:"Please select a Student.",indicator:"orange"}); return; }
		if(!from_date||!to_date){ frappe.msgprint({message:"Please set both dates.",indicator:"orange"}); return; }
		_gel("sl-area").innerHTML='<div class="sl-placeholder">Loading…</div>';
		_gel("sl-print-split").style.display="none";
		_gel("sl-excel-btn").style.display="none";
		this._lastData=null;
		var self=this;
		frappe.call({
			method:"dux_voucher.dux_voucher.api.reports_api.get_student_ledger",
			args:{company:company, kind:this._kind, student:student, from_date:from_date, to_date:to_date},
			callback:function(r){
				if(r.message){ self._lastData=r.message; self._render(r.message); _gel("sl-print-split").style.display="block"; _gel("sl-excel-btn").style.display="inline-flex"; }
				else{ _gel("sl-area").innerHTML='<div class="sl-placeholder">No data found for this student and period.</div>'; }
			},
			error:function(){ _gel("sl-area").innerHTML='<div class="sl-placeholder" style="color:#dc2626">Could not load the statement. Please try again.</div>'; },
		});
	}

	_render(d){
		var rows="";
		rows+=`<tr class="sl-tr-ob"><td colspan="4"><span class="sl-ob-label">Opening Balance</span></td><td class="sl-c-amt">${d.opening_debit>0?`<span class="sl-dr">${_fmt(d.opening_debit)}</span>`:'<span class="sl-nil">—</span>'}</td><td class="sl-c-amt">${d.opening_credit>0?`<span class="sl-cr">${_fmt(d.opening_credit)}</span>`:'<span class="sl-nil">—</span>'}</td><td class="sl-c-bal">${_bal(d.opening_balance,d.opening_type)}</td></tr>`;
		if(!d.rows.length) rows+=`<tr><td colspan="7" class="sl-placeholder" style="padding:32px">No transactions in this period.</td></tr>`;
		d.rows.forEach(function(row){
			var drHtml=row.debit>0?`<span class="sl-dr">${_fmt(row.debit)}</span>`:`<span class="sl-nil">—</span>`;
			var crHtml=row.credit>0?`<span class="sl-cr">${_fmt(row.credit)}</span>`:`<span class="sl-nil">—</span>`;
			var vno=row.voucher_url?`<a class="sl-vno" href="${_esc(row.voucher_url)}" target="_blank">${_esc(row.voucher_no)}</a>`:`<span class="sl-vno">${_esc(row.voucher_no)}</span>`;
			rows+=`<tr class="sl-tr-e"><td class="sl-c-date">${_esc(row.posting_date)}</td><td class="sl-c-part"><span class="sl-contra-name">${_esc(row.contra)}</span></td><td class="sl-c-vt">${_pill(row.voucher_type)}</td><td class="sl-c-vno">${vno}</td><td class="sl-c-amt">${drHtml}</td><td class="sl-c-amt">${crHtml}</td><td class="sl-c-bal">${_bal(row.balance,row.balance_type)}</td></tr>`;
			if(row.remarks) rows+=`<tr class="sl-tr-r"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
		});
		rows+=`<tr class="sl-tr-cb"><td colspan="4"><span class="sl-cb-label">Closing Balance</span></td><td class="sl-c-amt">${d.closing_balancing_debit>0?`<span class="sl-dr">${_fmt(d.closing_balancing_debit)}</span>`:'<span class="sl-nil">—</span>'}</td><td class="sl-c-amt">${d.closing_balancing_credit>0?`<span class="sl-cr">${_fmt(d.closing_balancing_credit)}</span>`:'<span class="sl-nil">—</span>'}</td><td class="sl-c-bal" style="font-size:13px">${_bal(d.closing_balance,d.closing_type)}</td></tr>`;
		rows+=`<tr class="sl-tr-tot"><td colspan="4" class="sl-tot-label">Total</td><td class="sl-c-amt"><span class="sl-dr">${_fmt(d.grand_total_debit)}</span></td><td class="sl-c-amt"><span class="sl-cr">${_fmt(d.grand_total_credit)}</span></td><td class="sl-c-bal"></td></tr>`;
		var badge=d.account_type?`<span class="sl-kind-badge">${_esc(d.account_type)}</span>`:"";
		_gel("sl-area").innerHTML=`
<div class="sl-report-card">
  <div class="sl-rpt-hdr">
    <div class="sl-rpt-co">${_esc(d.company)}</div>
    <div class="sl-rpt-ledger-row"><span>Ledger:</span><strong>${_esc(d.account_name)}</strong>${badge}</div>
    <div class="sl-rpt-period"><span>${_esc(d.from_date)}</span><span style="color:#d1d5db">→</span><span>${_esc(d.to_date)}</span><span style="color:#d1d5db">·</span><span>${d.row_count} transaction${d.row_count!==1?"s":""}</span></div>
    <div class="sl-legend"><b class="sl-lg-dr">Dr</b> = receivable due &nbsp;·&nbsp; <b class="sl-lg-cr">Cr</b> = fee held / advance</div>
  </div>
  <div class="sl-tbl-wrap">
    <table class="sl-tbl">
      <thead><tr>
        <th class="sl-c-date">Date</th><th class="sl-c-part">Particulars</th>
        <th class="sl-c-vt">Vch Type</th><th class="sl-c-vno">Vch No</th>
        <th class="sl-c-amt r">Debit</th><th class="sl-c-amt r">Credit</th>
        <th class="sl-c-bal r">Balance</th>
      </tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
	}

	/* ══════════════════════════════════════════════════════════
	   Excel export
	   ══════════════════════════════════════════════════════════ */
	_exportExcel(){
		if(!this._lastData) return;
		var company=_gel("sl-co-sel").value,
		    from_date=_gel("sl-from").value,
		    to_date=_gel("sl-to").value;
		var student=this._student?this._student.value:"";
		var params=new URLSearchParams({company:company, kind:this._kind, student:student, from_date:from_date, to_date:to_date});
		var url="/api/method/dux_voucher.dux_voucher.api.reports_export.export_student_ledger_xlsx?"+params.toString();
		window.location.href=url;
	}

	/* ══════════════════════════════════════════════════════════
	   Professional Print — clean new window
	   ══════════════════════════════════════════════════════════ */
	_printReport(landscape){
		if(!this._lastData) return;
		var d=this._lastData;
		var win=window.open("","_blank","width=1100,height=750");
		if(!win){ frappe.msgprint("Please allow pop-ups for this site."); return; }

		var pageRule=landscape
			? "@page{size:A4 landscape;margin:12mm 14mm 14mm}"
			: "@page{size:A4 portrait;margin:16mm 12mm 14mm}";

		var printedDate=new Date().toLocaleDateString("en-IN",{day:"2-digit",month:"long",year:"numeric"});

		var tRows="";

		tRows+=`<tr class="p-ob">
			<td colspan="4" class="p-ob-lbl">Opening Balance</td>
			<td class="p-num">${d.opening_debit>0?`<span class="p-dr">${_fmt(d.opening_debit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num">${d.opening_credit>0?`<span class="p-cr">${_fmt(d.opening_credit)}</span>`:'<span class="p-nil">—</span>'}</td>
			<td class="p-num p-fw ${d.opening_type==="Dr"?"p-dr":"p-cr"}">${_fmt(d.opening_balance)}<span class="p-suf">${d.opening_type}</span></td>
		</tr>`;

		d.rows.forEach(function(row,idx){
			var drHtml=row.debit>0?`<span class="p-dr">${_fmt(row.debit)}</span>`:'<span class="p-nil">—</span>';
			var crHtml=row.credit>0?`<span class="p-cr">${_fmt(row.credit)}</span>`:'<span class="p-nil">—</span>';
			var balCls=row.balance_type==="Dr"?"p-dr":"p-cr";
			tRows+=`<tr class="p-erow ${idx%2===0?"p-even":"p-odd"}">
				<td class="p-dt">${_esc(row.posting_date)}</td>
				<td class="p-part">${_esc(row.contra)}</td>
				<td class="p-vt">${_esc(row.voucher_type)}</td>
				<td class="p-vno">${_esc(row.voucher_no)}</td>
				<td class="p-num">${drHtml}</td>
				<td class="p-num">${crHtml}</td>
				<td class="p-num p-fw ${balCls}">${_fmt(row.balance)}<span class="p-suf">${row.balance_type}</span></td>
			</tr>`;
			if(row.remarks) tRows+=`<tr class="p-rmk"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
		});

		tRows+=`<tr class="p-cb">
			<td colspan="4" class="p-ob-lbl">Closing Balance</td>
			<td class="p-num">${d.closing_balancing_debit>0?`<span class="p-dr">${_fmt(d.closing_balancing_debit)}</span>`:'<span class="p-nil">—</span>'}</td><td class="p-num">${d.closing_balancing_credit>0?`<span class="p-cr">${_fmt(d.closing_balancing_credit)}</span>`:'<span class="p-nil">—</span>'}</td>
			<td class="p-num p-fw" style="font-size:12.5px;${d.closing_type==="Dr"?"color:#dc2626":"color:#16a34a"}">${_fmt(d.closing_balance)}<span class="p-suf">${d.closing_type}</span></td>
		</tr>`;

		tRows+=`<tr class="p-tot">
			<td colspan="4" class="p-tot-lbl">Total</td>
			<td class="p-num p-dr">${_fmt(d.grand_total_debit)}</td>
			<td class="p-num p-cr">${_fmt(d.grand_total_credit)}</td>
			<td class="p-num"></td>
		</tr>`;

		var badgeHtml=d.account_type?`<span class="p-badge">${_esc(d.account_type)}</span>`:"";

		win.document.write(`<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Student Ledger — ${_esc(d.account_name)}</title>
<style>
${pageRule}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:#fff;color:#1e293b}
body{font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:11px;line-height:1.45;padding:0}
.p-wrap{display:flex;flex-direction:column;min-height:100vh}
.p-hdr{display:flex;justify-content:space-between;align-items:flex-end;padding-bottom:10px;margin-bottom:14px;border-bottom:3px solid #0f172a}
.p-rtype{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.18em;color:#94a3b8;margin-bottom:5px}
.p-coname{font-size:21px;font-weight:800;color:#0f172a;letter-spacing:-.4px;line-height:1.1}
.p-hdr-right{text-align:right;font-size:9px;color:#94a3b8;padding-bottom:2px}
.p-info{display:flex;justify-content:space-between;align-items:center;background:#f8fafc;border:1px solid #e2e8f0;border-left:4.5px solid #0d9488;border-radius:0 6px 6px 0;padding:10px 16px;margin-bottom:8px}
.p-info-lbl{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#94a3b8;margin-bottom:4px}
.p-info-name{font-size:14px;font-weight:800;color:#0f172a;display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.p-badge{display:inline-block;font-size:8.5px;font-weight:700;background:#f0fdfa;color:#0f766e;border-radius:3px;padding:2px 7px;letter-spacing:.05em}
.p-info-right{text-align:right}
.p-period{font-size:10px;color:#475569;font-family:'Courier New',monospace;margin-bottom:2px}
.p-txncount{font-size:9px;color:#94a3b8}
.p-legend{font-size:9px;color:#94a3b8;margin-bottom:14px}
.p-legend b{font-weight:800}
*{-webkit-print-color-adjust:exact;print-color-adjust:exact}
table{width:100%;border-collapse:collapse}
thead tr{background:#1e293b}
thead th{font-size:8.5px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:#f1f5f9;padding:7px 9px;white-space:nowrap}
thead th.r{text-align:right}
.p-ob td{background:#ccfbf1;padding:8px 9px;border-top:1px solid #5eead4;border-bottom:1px solid #5eead4}
.p-cb td{background:#ccfbf1;padding:8px 9px;border-top:2.5px solid #0f172a;border-bottom:1px solid #5eead4}
.p-ob-lbl{font-size:9px;font-weight:800;text-transform:uppercase;letter-spacing:.1em;color:#115e59}
.p-even td{background:#fff;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-odd  td{background:#fafbfc;padding:6px 9px;border-bottom:1px solid #f1f5f9;vertical-align:top}
.p-rmk td{padding:0 9px 6px 22px;border-bottom:1px solid #f1f5f9;font-size:9px;color:#94a3b8;font-style:italic;line-height:1.5;overflow-wrap:anywhere;word-break:break-word}
.p-tot td{border-top:2.5px solid #0f172a;padding:8px 9px;font-weight:800;background:#f8fafc}
.p-tot-lbl{text-align:right;font-size:8.5px;text-transform:uppercase;letter-spacing:.1em;color:#64748b}
.p-dt{width:66px;color:#64748b;font-family:'Courier New',monospace;font-size:10px;white-space:nowrap}
.p-part{font-size:11px;color:#0f172a}
.p-vt{width:108px;font-size:10px;color:#374151;white-space:nowrap}
.p-vno{width:128px;font-family:'Courier New',monospace;font-size:10px;color:#0d9488;white-space:nowrap}
.p-num{width:94px;text-align:right;font-family:'Courier New',monospace;font-size:11px;white-space:nowrap}
.p-fw{font-weight:700}
.p-dr{color:#dc2626}
.p-cr{color:#16a34a}
.p-nil{color:#cbd5e1}
.p-suf{font-size:8px;margin-left:1px;font-weight:800;opacity:.7}
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
    <div class="p-rtype">Student Ledger</div>
    <div class="p-coname">${_esc(d.company)}</div>
  </div>
  <div class="p-hdr-right">Printed: ${_esc(printedDate)}</div>
</div>
<div class="p-info">
  <div>
    <div class="p-info-lbl">Student</div>
    <div class="p-info-name">${_esc(d.account_name)} ${badgeHtml}</div>
  </div>
  <div class="p-info-right">
    <div class="p-period">${_esc(d.from_date)}  →  ${_esc(d.to_date)}</div>
    <div class="p-txncount">${d.row_count} transaction${d.row_count!==1?"s":""}</div>
  </div>
</div>
<div class="p-legend"><b style="color:#dc2626">Dr</b> = receivable due &nbsp;·&nbsp; <b style="color:#16a34a">Cr</b> = fee held / advance</div>
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

/* ── Utilities (IIFE-local — do not collide with dux_ledger globals) ── */
function _gel(id){ return document.getElementById(id); }

function _fmt(val){
	return new Intl.NumberFormat("en-IN",{minimumFractionDigits:2,maximumFractionDigits:2}).format(val||0);
}

function _bal(val,type){
	if(!val) return '<span style="color:#9ca3af;font-family:monospace">0.00</span>';
	var cls=type==="Dr"?"sl-bal-dr":"sl-bal-cr";
	return `<span class="${cls}">${_fmt(val)}<span class="sl-bsuf">${type}</span></span>`;
}

function _pill(vtype){
	var m={
		"Fee Receipt":"sl-pill-receipt","Receipt":"sl-pill-receipt",
		"Fee Refund":"sl-pill-refund","Refund":"sl-pill-refund",
		"Opening Batch":"sl-pill-opening","Opening Balance":"sl-pill-opening",
		"Write-off":"sl-pill-writeoff",
	};
	return `<span class="sl-pill ${m[vtype]||"sl-pill-other"}">${_esc(vtype)}</span>`;
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
