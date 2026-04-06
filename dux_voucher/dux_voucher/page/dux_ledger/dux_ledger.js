frappe.pages["dux-ledger"].on_page_load = function(wrapper) {
    try {
        var page = frappe.ui.make_app_page({
            parent: wrapper,
            title: "Ledger Statement",
            single_column: true,
        });
        $(wrapper).find(".layout-main-section").html("<div style='padding:40px;font-size:18px;color:green'>make_app_page worked. Now loading full app...</div>");
        window._dux_ledger_instance = new DuxLedger(wrapper, page);
    } catch(e) {
        $(wrapper).append("<div style='padding:40px;color:red;font-size:14px'>on_page_load ERROR: " + e.message + "<br><pre>" + e.stack + "</pre></div>");
        console.error("dux-ledger error:", e);
    }
};

frappe.pages["dux-ledger"].on_page_show = function(wrapper) {
    if (window._dux_ledger_instance && frappe.route_options) {
        window._dux_ledger_instance.applyRouteOptions(frappe.route_options);
        frappe.route_options = null;
    }
};

class DuxLedger {
    constructor(wrapper, page) {
        this.wrapper = wrapper;
        this.page    = page;
        this._injectStyles();
        this._renderLayout();
        this._bindEvents();
        this._setDefaultDates();
        this._loadCompanies();

        // Home button in the page toolbar
        page.add_inner_button("← Home", function () {
            window.location.href = "/rgi-home";
        });
    }

    /* ── CSS ────────────────────────────────────────────────────── */
    _injectStyles() {
        if (document.getElementById("dux-ledger-styles")) return;
        var s = document.createElement("style");
        s.id = "dux-ledger-styles";
        s.textContent = `
/* Filter bar */
.dux-filter-bar{display:flex;flex-wrap:wrap;align-items:flex-end;gap:12px;padding:16px 0 20px;border-bottom:1px solid var(--border-color);margin-bottom:20px}
.dux-fg{display:flex;flex-direction:column;gap:4px}
.dux-fg label{font-size:11px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.07em}
.dux-fg select,.dux-fg input{height:32px;border:1px solid var(--border-color);border-radius:var(--border-radius,6px);padding:0 9px;font-size:13px;background:var(--control-bg,#fff);color:var(--text-color);outline:none;box-sizing:border-box;font-family:var(--font-stack)}
.dux-fg select:focus,.dux-fg input:focus{border-color:var(--primary)}
#dux-co-sel{min-width:230px}
#dux-acc-inp{min-width:270px}
#dux-from,#dux-to{width:140px}
.dux-btn{height:32px;padding:0 16px;border-radius:var(--border-radius,6px);border:1px solid var(--border-color);font-size:13px;cursor:pointer;background:var(--control-bg,#fff);color:var(--text-color);font-family:var(--font-stack)}
.dux-btn-primary{background:var(--primary);border-color:var(--primary);color:#fff;font-weight:500}
.dux-btn-primary:hover{filter:brightness(1.07)}
.dux-btn:not(.dux-btn-primary):hover{background:var(--gray-100,#f3f4f6)}

/* Loading / placeholder */
.dux-placeholder,.dux-loading{text-align:center;padding:60px 20px;color:var(--text-muted);font-size:14px;font-family:var(--font-stack)}
.dux-err{color:#c0392b}

/* Report card */
.dux-report{background:var(--card-bg,#fff);border:1px solid var(--border-color);border-radius:8px;overflow:hidden;margin-bottom:24px}

/* Report header */
.dux-rpt-hdr{padding:14px 20px 12px;border-bottom:1px solid var(--border-color)}
.dux-rpt-co{font-size:15px;font-weight:600;color:var(--text-color);margin-bottom:2px}
.dux-rpt-ledger{font-size:13px;color:var(--text-muted);margin-bottom:2px}
.dux-rpt-period{font-size:11px;color:var(--text-muted);font-family:'SFMono-Regular',Consolas,monospace}
.dux-acc-badge{display:inline-block;font-size:10px;background:var(--blue-100,#dbeafe);color:var(--blue-700,#1d4ed8);border-radius:3px;padding:1px 6px;margin-left:6px;vertical-align:middle;font-family:var(--font-stack)}

/* Table */
.dux-tbl-wrap{overflow-x:auto}
.dux-tbl{width:100%;border-collapse:collapse;font-size:12.5px;font-family:'SFMono-Regular',Consolas,'Courier New',monospace}
.dux-tbl thead th{font-family:var(--font-stack);font-size:10px;font-weight:600;text-transform:uppercase;letter-spacing:.07em;color:var(--text-muted);padding:8px 12px;background:var(--gray-50,#f9fafb);border-bottom:1px solid var(--border-color);white-space:nowrap}
.dux-tbl thead th.r{text-align:right}

/* Entry row */
.dux-tr-e td{padding:8px 12px;border-bottom:1px solid var(--border-color);vertical-align:top}
.dux-tr-e:hover td{background:var(--gray-50,#f9fafb)}

/* Remarks sub-row */
.dux-tr-r td{padding:2px 12px 7px 28px;border-bottom:1px solid var(--border-color);font-family:var(--font-stack);font-size:11px;color:var(--text-muted);font-style:italic}

/* Opening / Closing balance rows */
.dux-tr-ob td,.dux-tr-cb td{padding:8px 12px;background:var(--gray-50,#f9fafb);font-family:var(--font-stack);font-size:12px;font-weight:600}
.dux-tr-ob td{border-bottom:1px solid var(--border-color)}
.dux-tr-cb td{border-top:2px solid var(--border-color)}

/* Totals row */
.dux-tr-tot td{padding:8px 12px;border-top:1px solid var(--border-color);font-size:12.5px;font-weight:600}

/* Cell widths */
.dux-c-date{width:76px;color:var(--text-muted);white-space:nowrap}
.dux-c-part{min-width:160px}
.dux-c-vt{width:118px;white-space:nowrap}
.dux-c-vno{width:112px;white-space:nowrap}
.dux-c-amt{width:100px;text-align:right;white-space:nowrap}
.dux-c-bal{width:115px;text-align:right;white-space:nowrap}

/* To / By prefix */
.dux-to{color:#185FA5;font-weight:500}
.dux-by{color:#0F6E56;font-weight:500}
.dux-contra-sub{font-size:11px;color:var(--text-muted);margin-top:1px;font-family:var(--font-stack)}

/* Voucher No link */
.dux-vno{color:var(--primary);text-decoration:none;font-size:12px}
.dux-vno:hover{text-decoration:underline}

/* Amounts */
.dux-dr{color:#c0392b}
.dux-cr{color:#196f3d}
.dux-nil{color:var(--text-muted)}
.dux-bal-dr{color:#c0392b;font-weight:500}
.dux-bal-cr{color:#196f3d;font-weight:500}
.dux-bsuf{font-size:10px;margin-left:3px;font-family:var(--font-stack);opacity:.75}

/* Voucher type pills */
.dux-pill{display:inline-block;font-size:10px;font-family:var(--font-stack);padding:2px 7px;border-radius:3px;white-space:nowrap;font-weight:500}
.dux-pv{background:#eff6ff;color:#1d4ed8}
.dux-rv{background:#f0fdf4;color:#166534}
.dux-jv{background:#fffbeb;color:#92400e}
.dux-cv{background:#f3f4f6;color:#374151;border:1px solid #d1d5db}
.dux-pe{background:#fdf4ff;color:#7e22ce}
.dux-re{background:#f0fdf4;color:#166534}

/* Print */
@media print{
.dux-filter-bar,.dux-no-print,.page-head,.layout-side-section,.navbar,header,
button,.dux-btn{display:none!important}
.dux-report{border:none;box-shadow:none;border-radius:0}
.dux-tbl{font-size:11px}
.dux-tr-e td,.dux-tr-r td{padding:5px 8px}
.dux-pill{-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{background:#fff!important}
}
        `;
        document.head.appendChild(s);
    }

    /* ── Layout ─────────────────────────────────────────────────── */
    _renderLayout() {
        $(this.wrapper).find(".layout-main-section").html(`
<div class="dux-filter-bar">
  <div class="dux-fg">
    <label>Company</label>
    <select id="dux-co-sel"><option value="">Select company…</option></select>
  </div>
  <div class="dux-fg">
    <label>Account / Ledger</label>
    <input id="dux-acc-inp" type="text" placeholder="Type to search…" autocomplete="off" list="dux-acc-dl">
    <datalist id="dux-acc-dl"></datalist>
  </div>
  <div class="dux-fg">
    <label>From</label>
    <input id="dux-from" type="date">
  </div>
  <div class="dux-fg">
    <label>To</label>
    <input id="dux-to" type="date">
  </div>
  <div class="dux-fg" style="justify-content:flex-end">
    <label>&nbsp;</label>
    <div style="display:flex;gap:8px">
      <button class="dux-btn dux-btn-primary" id="dux-show">Show</button>
      <button class="dux-btn dux-no-print" id="dux-print" style="display:none">Print</button>
    </div>
  </div>
</div>
<div id="dux-area">
  <div class="dux-placeholder">Select a company and account, then click <strong>Show</strong>.</div>
</div>
        `);
    }

    /* ── Events ─────────────────────────────────────────────────── */
    _bindEvents() {
        var self = this;

        // Company change → clear account field
        _el("dux-co-sel").addEventListener("change", function () {
            _el("dux-acc-inp").value = "";
            _el("dux-acc-dl").innerHTML = "";
        });

        // Account type-ahead
        _el("dux-acc-inp").addEventListener("input", _debounce(function () {
            var co  = _el("dux-co-sel").value;
            var txt = this.value.trim();
            if (co && txt.length >= 2) self._searchAccounts(co, txt);
        }, 300));

        // Show button
        _el("dux-show").addEventListener("click",  function () { self.fetchReport(); });

        // Print button
        _el("dux-print").addEventListener("click", function () { window.print(); });

        // Enter key in any filter triggers Show
        ["dux-co-sel", "dux-acc-inp", "dux-from", "dux-to"].forEach(function (id) {
            _el(id).addEventListener("keydown", function (ev) {
                if (ev.key === "Enter") self.fetchReport();
            });
        });
    }

    /* ── Default dates (Indian FY: April 1 → today) ─────────────── */
    _setDefaultDates() {
        var now   = new Date();
        var m     = now.getMonth();       // 0-based; March = 2
        var yr    = now.getFullYear();
        var fyStart = m >= 3 ? yr : yr - 1;
        _el("dux-from").value = fyStart + "-04-01";
        _el("dux-to").value   = now.toISOString().split("T")[0];
    }

    /* ── Load companies (respects User Permissions) ──────────────── */
    _loadCompanies() {
        var self = this;
        frappe.call({
            method: "frappe.auth.get_logged_user",
            callback: function (r) {
                var email = r.message;
                if (!email || email === "Guest") return;
                frappe.call({
                    method: "frappe.client.get_list",
                    args: {
                        doctype: "User Permission",
                        filters: [["user", "=", email], ["allow", "=", "Company"]],
                        fields: ["for_value"],
                        limit_page_length: 200,
                    },
                    callback: function (r2) {
                        var items = r2.message || [];
                        if (items.length) {
                            self._populateCompanies(items.map(function (p) { return p.for_value; }));
                        } else {
                            // System Manager — fetch all companies
                            frappe.call({
                                method: "frappe.client.get_list",
                                args: {
                                    doctype: "Company",
                                    filters: [["is_group", "=", 0]],
                                    fields: ["name"],
                                    limit_page_length: 200,
                                    order_by: "name asc",
                                },
                                callback: function (r3) {
                                    self._populateCompanies((r3.message || []).map(function (c) { return c.name; }));
                                },
                            });
                        }
                    },
                });
            },
        });
    }

    _populateCompanies(names) {
        var sel = _el("dux-co-sel");
        names.forEach(function (n) {
            sel.innerHTML += `<option value="${_esc(n)}">${_esc(n)}</option>`;
        });
        // Pre-fill from route options if present
        var opts = frappe.route_options || {};
        if (opts.company) sel.value = opts.company;
        if (opts.account) _el("dux-acc-inp").value = opts.account;
        if (opts.from_date) _el("dux-from").value = opts.from_date;
        if (opts.to_date)   _el("dux-to").value   = opts.to_date;
        if (opts.company && opts.account) this.fetchReport();
        frappe.route_options = null;
    }

    /* ── Account type-ahead ──────────────────────────────────────── */
    _searchAccounts(company, txt) {
        frappe.call({
            method: "dux_voucher.dux_voucher.api.reports_api.get_accounts_for_company",
            args: { company: company, search_txt: txt },
            callback: function (r) {
                var dl = _el("dux-acc-dl");
                dl.innerHTML = "";
                (r.message || []).forEach(function (a) {
                    var o = document.createElement("option");
                    o.value = a.name;
                    dl.appendChild(o);
                });
            },
        });
    }

    /* ── Public: pre-fill from route options ─────────────────────── */
    applyRouteOptions(opts) {
        if (opts.company)    _el("dux-co-sel").value      = opts.company;
        if (opts.account)    _el("dux-acc-inp").value     = opts.account;
        if (opts.from_date)  _el("dux-from").value        = opts.from_date;
        if (opts.to_date)    _el("dux-to").value          = opts.to_date;
        if (opts.company && opts.account) this.fetchReport();
    }

    /* ── Fetch report from API ───────────────────────────────────── */
    fetchReport() {
        var company   = _el("dux-co-sel").value;
        var account   = _el("dux-acc-inp").value.trim();
        var from_date = _el("dux-from").value;
        var to_date   = _el("dux-to").value;

        if (!company)   { frappe.msgprint("Please select a Company.");          return; }
        if (!account)   { frappe.msgprint("Please enter an Account name.");     return; }
        if (!from_date || !to_date) { frappe.msgprint("Please set both dates."); return; }

        _el("dux-area").innerHTML = "<div class='dux-loading'>Loading…</div>";
        _el("dux-print").style.display = "none";

        var self = this;
        frappe.call({
            method: "dux_voucher.dux_voucher.api.reports_api.get_ledger_statement",
            args: { company, account, from_date, to_date },
            freeze: false,
            callback: function (r) {
                if (r.message) {
                    self._render(r.message);
                    _el("dux-print").style.display = "inline-block";
                } else {
                    _el("dux-area").innerHTML = "<div class='dux-placeholder'>No data returned. Check the account name and company.</div>";
                }
            },
            error: function () {
                _el("dux-area").innerHTML = "<div class='dux-placeholder dux-err'>Could not load report. Check the account name and try again.</div>";
            },
        });
    }

    /* ── Render the report ───────────────────────────────────────── */
    _render(d) {
        var rows = "";

        // Opening Balance
        rows += `
<tr class="dux-tr-ob">
  <td colspan="4" style="color:var(--text-muted)">Opening Balance</td>
  <td class="dux-c-amt"></td>
  <td class="dux-c-amt"></td>
  <td class="dux-c-bal">${_bal(d.opening_balance, d.opening_type)}</td>
</tr>`;

        if (!d.rows.length) {
            rows += `<tr><td colspan="7" class="dux-placeholder">No transactions in this period.</td></tr>`;
        }

        d.rows.forEach(function (row) {
            var pCls = row.prefix === "To" ? "dux-to" : "dux-by";
            var drHtml = row.debit  > 0 ? `<span class="dux-dr">${_fmt(row.debit)}</span>`  : `<span class="dux-nil">—</span>`;
            var crHtml = row.credit > 0 ? `<span class="dux-cr">${_fmt(row.credit)}</span>` : `<span class="dux-nil">—</span>`;

            rows += `
<tr class="dux-tr-e">
  <td class="dux-c-date">${_esc(row.posting_date)}</td>
  <td class="dux-c-part">
    <span class="${pCls}">${row.prefix}</span> ${_esc(row.contra)}
  </td>
  <td class="dux-c-vt">${_pill(row.voucher_type)}</td>
  <td class="dux-c-vno">
    <a class="dux-vno" href="${_esc(row.voucher_url)}" target="_blank">${_esc(row.voucher_no)}</a>
  </td>
  <td class="dux-c-amt">${drHtml}</td>
  <td class="dux-c-amt">${crHtml}</td>
  <td class="dux-c-bal">${_bal(row.balance, row.balance_type)}</td>
</tr>`;

            if (row.remarks) {
                rows += `<tr class="dux-tr-r"><td colspan="7">${_esc(row.remarks)}</td></tr>`;
            }
        });

        // Closing Balance
        rows += `
<tr class="dux-tr-cb">
  <td colspan="4" style="color:var(--text-muted)">Closing Balance</td>
  <td class="dux-c-amt"></td>
  <td class="dux-c-amt"></td>
  <td class="dux-c-bal" style="font-size:13px">${_bal(d.closing_balance, d.closing_type)}</td>
</tr>`;

        // Totals
        rows += `
<tr class="dux-tr-tot">
  <td colspan="4" style="text-align:right;font-family:var(--font-stack);font-size:11px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em">Totals</td>
  <td class="dux-c-amt"><span class="dux-dr">${_fmt(d.total_debit)}</span></td>
  <td class="dux-c-amt"><span class="dux-cr">${_fmt(d.total_credit)}</span></td>
  <td class="dux-c-bal"></td>
</tr>`;

        var badge = d.account_type
            ? `<span class="dux-acc-badge">${_esc(d.account_type)}</span>`
            : "";

        _el("dux-area").innerHTML = `
<div class="dux-report">
  <div class="dux-rpt-hdr">
    <div class="dux-rpt-co">${_esc(d.company)}</div>
    <div class="dux-rpt-ledger">Ledger: <strong>${_esc(d.account_name)}</strong>${badge}</div>
    <div class="dux-rpt-period">${_esc(d.from_date)} — ${_esc(d.to_date)}&nbsp;&nbsp;·&nbsp;&nbsp;${d.row_count} transaction${d.row_count !== 1 ? "s" : ""}</div>
  </div>
  <div class="dux-tbl-wrap">
    <table class="dux-tbl">
      <thead>
        <tr>
          <th class="dux-c-date">Date</th>
          <th class="dux-c-part">Particulars</th>
          <th class="dux-c-vt">Vch Type</th>
          <th class="dux-c-vno">Vch No</th>
          <th class="dux-c-amt r">Debit</th>
          <th class="dux-c-amt r">Credit</th>
          <th class="dux-c-bal r">Balance</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
    }
}

/* ============================================================
   Pure utility functions (no 'this' dependency)
   ============================================================ */

function _el(id) { return document.getElementById(id); }

function _fmt(val) {
    return new Intl.NumberFormat("en-IN", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    }).format(val || 0);
}

function _bal(val, type) {
    if (!val) return `<span class="dux-nil">0.00</span>`;
    var cls = type === "Dr" ? "dux-bal-dr" : "dux-bal-cr";
    return `<span class="${cls}">${_fmt(val)}<span class="dux-bsuf">${type}</span></span>`;
}

function _pill(vtype) {
    var clsMap = {
        "Payment Voucher": "dux-pv",
        "Receipt Voucher": "dux-rv",
        "Journal Entry":   "dux-jv",
        "Contra Entry":    "dux-cv",
        "Payment Entry":   "dux-pe",
        "Receipt Entry":   "dux-re",
    };
    var cls = clsMap[vtype] || "dux-cv";
    return `<span class="dux-pill ${cls}">${_esc(vtype)}</span>`;
}

function _esc(str) {
    if (str === null || str === undefined) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function _debounce(fn, ms) {
    var t;
    return function () {
        var ctx = this, args = arguments;
        clearTimeout(t);
        t = setTimeout(function () { fn.apply(ctx, args); }, ms);
    };
}
