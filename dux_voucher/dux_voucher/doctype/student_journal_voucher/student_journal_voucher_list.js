/* Student Journal Voucher — list view.
   "Bulk Create" makes one DRAFT voucher per student (one voucher per
   student is the rule): preview first, then create. The drafts are then
   reviewed and submitted from this list — Frappe runs a large bulk submit
   in the background. */

const SJV_LIST_METHOD = "dux_voucher.dux_voucher.doctype.student_journal_voucher.student_journal_voucher.";

frappe.listview_settings["Student Journal Voucher"] = {
    add_fields: ["purpose", "total_amount", "docstatus"],
    get_indicator(doc) {
        if (doc.docstatus === 2) return [__("Cancelled"), "red", "docstatus,=,2"];
        if (doc.docstatus === 0) return [__("Draft"), "orange", "docstatus,=,0"];
        const credit = ["Concession", "Other Credit to Student"].includes(doc.purpose);
        return [__(doc.purpose), credit ? "green" : "blue", "purpose,=," + doc.purpose];
    },
    onload(listview) {
        listview.page.add_inner_button(__("Bulk Create"), () => sjv_bulk_dialog(listview));
    },
};

function sjv_bulk_dialog(listview) {
    let preview = null;
    let previewed_with = null;   // the inputs the shown preview was built from
    let selected = new Set();    // students ticked in the preview
    const roots = { "Fee Charged": ["Income", "Liability"], "Fine / Penalty": ["Income"], "Concession": ["Income", "Expense"] };
    const is_transfer = () => d.get_value("purpose") === "Transfer to Institute";

    const d = new frappe.ui.Dialog({
        title: __("Bulk Create Student Journal Vouchers"),
        size: "extra-large",
        fields: [
            { fieldname: "company", fieldtype: "Link", options: "Company", label: __("Company"), reqd: 1,
              get_query: () => ({ filters: { is_group: 0 } }), onchange: () => reset() },
            { fieldname: "purpose", fieldtype: "Select", label: __("Purpose"), reqd: 1,
              options: ["", "Transfer to Institute", "Fee Charged", "Fine / Penalty", "Concession",
                        "Other Debit to Student", "Other Credit to Student"].join("\n"),
              onchange: () => reset() },
            { fieldtype: "Column Break" },
            { fieldname: "posting_date", fieldtype: "Date", label: __("Posting Date"), reqd: 1,
              default: frappe.datetime.get_today() },
            { fieldname: "course", fieldtype: "Link", options: "Course", label: __("Course (optional)"),
              onchange: () => reset() },

            { fieldtype: "Section Break", label: __("Transfer"), depends_on: "eval:doc.purpose=='Transfer to Institute'" },
            { fieldname: "to_company", fieldtype: "Link", options: "Company", label: __("Transfer To Institute"),
              ignore_user_permissions: 1,
              get_query: () => ({ filters: { is_group: 0, name: ["!=", d.get_value("company") || ""] } }),
              onchange: () => load_default_account() },
            { fieldname: "to_account", fieldtype: "Link", options: "Account", label: __("Ledger Credited at Institute"),
              ignore_user_permissions: 1,
              get_query: () => ({ filters: { company: d.get_value("to_company") || "__none__", is_group: 0, disabled: 0,
                                             account_type: ["not in", ["Bank", "Cash", "Receivable", "Payable"]],
                                             root_type: ["in", ["Asset", "Liability"]] } }) },
            { fieldtype: "Column Break" },
            { fieldname: "amount_mode", fieldtype: "Select", label: __("Amount"),
              options: "Full balance\nFixed amount", default: "Full balance", onchange: () => reset() },
            { fieldname: "amount", fieldtype: "Currency", label: __("Fixed Amount per Student"),
              depends_on: "eval:doc.amount_mode=='Fixed amount'", onchange: () => reset() },

            { fieldtype: "Section Break", label: __("Ledgers (same for every student)"),
              depends_on: "eval:doc.purpose && doc.purpose!='Transfer to Institute'" },
            { fieldname: "heads", fieldtype: "Table", label: __("Ledgers"), cannot_add_rows: false, in_place_edit: true,
              data: [], fields: [
                  { fieldname: "account", fieldtype: "Link", options: "Account", label: __("Ledger"), in_list_view: 1, reqd: 1,
                    get_query: () => {
                        const r = roots[d.get_value("purpose")];
                        const f = { company: d.get_value("company") || "__none__", is_group: 0, disabled: 0,
                                    account_type: ["not in", r ? ["Receivable", "Payable"]
                                                              : ["Bank", "Cash", "Receivable", "Payable"]] };
                        if (r) f.root_type = ["in", r];
                        return { filters: f };
                    } },
                  { fieldname: "amount", fieldtype: "Currency", label: __("Amount"), in_list_view: 1, reqd: 1 },
              ] },
            { fieldname: "skip_existing", fieldtype: "Check", default: 1,
              label: __("Skip students who already have a voucher of this purpose this financial year") },

            { fieldtype: "Section Break" },
            { fieldname: "remarks", fieldtype: "Small Text", label: __("Narration (optional, same for all)") },
            { fieldtype: "Section Break", label: __("Preview") },
            { fieldname: "preview_html", fieldtype: "HTML" },
        ],
        primary_action_label: __("Preview"),
        primary_action: () => (preview ? create() : run_preview()),
    });

    function params() {
        const v = d.get_values(true) || {};
        v.heads = (d.fields_dict.heads.df.data || []).filter(h => h.account && flt(h.amount) > 0)
            .map(h => ({ account: h.account, amount: flt(h.amount) }));
        return v;
    }

    function reset() {
        preview = null;
        selected = new Set();
        d.set_primary_action(__("Preview"), () => run_preview());
        d.fields_dict.preview_html.$wrapper.empty();
    }

    function load_default_account() {
        reset();
        const co = d.get_value("company"), to = d.get_value("to_company");
        if (!co || !to) return;
        frappe.call({
            method: SJV_LIST_METHOD + "get_context",
            args: { company: co, to_company: to },
            callback: (r) => {
                const m = r.message || {};
                if (m.to_account_default && !d.get_value("to_account")) d.set_value("to_account", m.to_account_default);
                if (m.branch_error) frappe.msgprint({ message: m.branch_error, indicator: "red" });
            },
        });
    }

    function run_preview() {
        const v = params();
        if (!v.company || !v.purpose) { frappe.msgprint(__("Select Company and Purpose.")); return; }
        if (is_transfer() && (!v.to_company || !v.to_account)) {
            frappe.msgprint(__("Select the institute and the ledger credited there.")); return;
        }
        if (!is_transfer() && !v.heads.length) { frappe.msgprint(__("Add at least one ledger row.")); return; }
        frappe.call({
            method: SJV_LIST_METHOD + "bulk_preview",
            args: { params: v },
            freeze: true,
            callback: (r) => {
                preview = r.message;
                previewed_with = JSON.stringify(v);
                // Every eligible student starts ticked; the operator unticks
                // whoever should be left out (or clears and picks a few).
                selected = new Set(preview.rows.filter(x => x.ok).map(x => x.student));
                render_preview();
            },
        });
    }

    function render_preview() {
        const fmt = (x) => format_currency(Math.abs(flt(x)), "INR");
        const bal = (x) => Math.abs(flt(x)) < 0.005 ? "Nil" : fmt(x) + (flt(x) > 0 ? " Cr" : " Dr");
        const esc = frappe.utils.escape_html;
        const rows = preview.rows.map(x => `<tr class="sjv-bk-row" data-student="${esc(x.student)}"
                data-search="${esc(((x.student_name || "") + " " + x.student + " " + (x.course || "")).toLowerCase())}"
                style="${x.ok ? "" : "color:#94a3b8"}">
            <td style="padding:3px 6px;width:28px"><input type="checkbox" class="sjv-bk-tick" ${x.ok ? "" : "disabled"}
                ${selected.has(x.student) ? "checked" : ""}></td>
            <td style="padding:3px 6px">${esc(x.student_name || x.student)} <span style="color:#94a3b8">${esc(x.student)}</span></td>
            <td style="padding:3px 6px">${esc(x.course || "")}</td>
            <td style="padding:3px 6px;text-align:right">${bal(x.balance)}</td>
            <td style="padding:3px 6px;text-align:right">${x.ok ? fmt(x.amount) : ""}</td>
            <td style="padding:3px 6px">${esc(x.note || "")}</td></tr>`).join("");
        const $w = d.fields_dict.preview_html.$wrapper;
        $w.html(`
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:8px">
              <input type="text" class="form-control input-sm sjv-bk-search" style="max-width:260px"
                     placeholder="${__("Search student, ID or course…")}">
              <button class="btn btn-xs btn-default sjv-bk-all">${__("Select all")}</button>
              <button class="btn btn-xs btn-default sjv-bk-none">${__("Clear")}</button>
              <span class="sjv-bk-count" style="font-size:12px;margin-left:auto"></span>
            </div>
            <div class="sjv-bk-scroll" style="max-height:320px;overflow:auto;border:1px solid #e2e8f0;border-radius:6px">
            <table style="width:100%;font-size:12px;border-collapse:collapse">
              <tr style="background:#f8fafc;color:#64748b"><th style="padding:4px 6px"></th>
                <th style="text-align:left;padding:4px 6px">Student</th>
                <th style="text-align:left;padding:4px 6px">Course</th><th style="text-align:right;padding:4px 6px">Balance</th>
                <th style="text-align:right;padding:4px 6px">Amount</th><th style="text-align:left;padding:4px 6px">Note</th></tr>
              ${rows || `<tr><td colspan="6" style="padding:8px">No students found.</td></tr>`}
            </table></div>
            <div style="font-size:11px;color:#64748b;margin-top:6px">
              ${__("Untick anyone to leave them out. Select all / Clear act on the students shown by the search. Greyed rows cannot be posted.")}</div>`);

        const visible_ok = () => $w.find(".sjv-bk-row:visible .sjv-bk-tick:not(:disabled)");
        $w.find(".sjv-bk-search").on("input", function () {
            const q = (this.value || "").trim().toLowerCase();
            $w.find(".sjv-bk-row").each(function () {
                $(this).toggle(!q || this.dataset.search.includes(q));
            });
        });
        $w.off("change.sjvbk").on("change.sjvbk", ".sjv-bk-tick", function () {
            const s = $(this).closest(".sjv-bk-row").attr("data-student");
            this.checked ? selected.add(s) : selected.delete(s);
            update_count();
        });
        $w.find(".sjv-bk-all").on("click", () => {
            visible_ok().each(function () { this.checked = true; selected.add($(this).closest(".sjv-bk-row").attr("data-student")); });
            update_count();
        });
        $w.find(".sjv-bk-none").on("click", () => {
            visible_ok().each(function () { this.checked = false; selected.delete($(this).closest(".sjv-bk-row").attr("data-student")); });
            update_count();
        });
        update_count();
    }

    function update_count() {
        const amount = preview.rows.filter(x => x.ok && selected.has(x.student))
            .reduce((s, x) => s + flt(x.amount), 0);
        d.fields_dict.preview_html.$wrapper.find(".sjv-bk-count").html(
            __("<b>{0}</b> of {1} selected · total <b>{2}</b>",
               [selected.size, preview.eligible, format_currency(amount, "INR")]));
        if (selected.size) {
            d.set_primary_action(__("Create {0} Drafts", [selected.size]), () => create());
            d.get_primary_btn().prop("disabled", false);
        } else {
            d.set_primary_action(__("Create Drafts"), () => {});
            d.get_primary_btn().prop("disabled", true);
        }
    }

    function create() {
        // Ledgers / narration / dates edited after the preview? Show the
        // new preview first — never create something nobody has looked at.
        if (JSON.stringify(params()) !== previewed_with) {
            run_preview();
            return;
        }
        if (!selected.size) return;
        frappe.call({
            method: SJV_LIST_METHOD + "bulk_create",
            args: { params: Object.assign(params(), { students: [...selected] }) },
            freeze: true,
            freeze_message: __("Creating vouchers…"),
            callback: (r) => {
                const m = r.message || { created: [], failed: [] };
                let msg = __("{0} draft voucher(s) created.", [m.created.length]);
                if (m.failed.length) {
                    msg += "<br><br><b>" + __("Not created") + ":</b><br>" + m.failed.map(f =>
                        `${frappe.utils.escape_html(f.student_name || f.student)} — ${frappe.utils.escape_html(f.error)}`).join("<br>");
                }
                frappe.msgprint({ title: __("Bulk Create"), message: msg, indicator: m.failed.length ? "orange" : "green" });
                d.hide();
                listview.refresh();
            },
        });
    }

    d.show();
}
