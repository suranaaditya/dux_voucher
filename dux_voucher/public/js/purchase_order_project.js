// Purchase Order — Set Project on a submitted PO and everything made from it.
// Loaded for both the form (doctype_js) and the list (doctype_list_js), so
// every block below guards against running twice. The server decides what
// changes and re-checks everything on Apply (api/project_tagging.py).
frappe.provide("dux_voucher.project_tagging");

(function () {
    const NS = dux_voucher.project_tagging;
    const M = "dux_voucher.dux_voucher.api.project_tagging";

    if (!NS.open) {
        NS.can = () => frappe.user.has_role(["System Manager", "Accounts Manager"]);

        // opts: rows [{purchase_order, project?}], ask_project, company, project, title, after_apply
        NS.open = function (opts) {
            const fields = [];
            if (opts.ask_project) {
                fields.push({
                    fieldname: "project", fieldtype: "Link", options: "Project", reqd: 1,
                    label: __("Project"), default: opts.project || "",
                    get_query: () => ({ filters: Object.assign(
                        { status: ["!=", "Cancelled"] },
                        opts.company ? { company: opts.company } : {}) }),
                    onchange: () => to_preview(),
                });
            }
            fields.push(
                { fieldname: "overwrite", fieldtype: "Check", onchange: () => to_preview(),
                  label: __("Replace a different project where one is already set") },
                { fieldname: "result", fieldtype: "HTML" },
            );
            const d = new frappe.ui.Dialog({
                title: opts.title || __("Set Project"), size: "extra-large", fields,
            });
            const html = d.fields_dict.result.$wrapper;
            html.html(`<div class="text-muted small">${__(
                "Preview first: it lists every GRN, invoice and payment made from these orders and "
                + "exactly what will change. Nothing is saved until you press Apply.")}</div>`);

            const rows = () => opts.rows.map((r) => Object.assign({}, r,
                opts.ask_project ? { project: d.get_value("project") } : {}));
            // Apply sends exactly what was previewed — never a value edited since.
            let previewed = null;

            function to_preview() {
                previewed = null;
                d.set_primary_action(__("Preview"), preview);
            }
            function preview() {
                if (opts.ask_project && !d.get_value("project")) {
                    return frappe.msgprint(__("Choose the project first."));
                }
                const args = { rows: JSON.stringify(rows()), overwrite: d.get_value("overwrite") ? 1 : 0 };
                frappe.call({ method: M + ".preview", args, freeze: true,
                              freeze_message: __("Following the links…") })
                    .then((r) => {
                        html.html(NS.render(r.message, false));
                        if (r.message.totals.orders || r.message.documents.length) {
                            previewed = { args, res: r.message };
                            d.set_primary_action(__("Apply"), apply);
                        } else {
                            to_preview();
                        }
                    });
            }
            function apply() {
                if (!previewed) return preview();
                const { args, res } = previewed;
                const t = res.totals;
                const project = opts.ask_project
                    ? (res.project_names || {})[d.get_value("project")] || d.get_value("project")
                    : __("the projects in the sheet");
                frappe.confirm(__(
                    "Set {0} on {1} order(s), {2} GRN(s), {3} invoice(s), {4} payment(s) and their ledger rows?",
                    [frappe.utils.escape_html(project), t.orders, t.receipts, t.invoices, t.payments]), () => {
                    frappe.call({ method: M + ".apply", args, freeze: true,
                                  freeze_message: __("Tagging…") })
                        .then((r) => {
                            html.html(NS.render(r.message, true));
                            d.set_primary_action(__("Close"), () => d.hide());
                            opts.after_apply && opts.after_apply(r.message);
                        });
                });
            }
            to_preview();
            d.show();
            if (!opts.ask_project) preview();
            return d;
        };

        NS.upload = function (after_apply) {
            new frappe.ui.FileUploader({
                allow_multiple: false,
                restrictions: { allowed_file_types: [".xlsx", ".csv"] },
                disable_file_browser: true,
                allow_web_link: false,
                allow_take_photo: false,
                allow_google_drive: false,
                make_attachments_public: false,
                allow_toggle_private: false,
                on_success(file) {
                    frappe.call({ method: M + ".read_sheet", args: { file_url: file.file_url },
                                  freeze: true })
                        .then((r) => {
                            const rows = r.message.rows || [];
                            if (!rows.length) return frappe.msgprint(__("The sheet has no PO numbers."));
                            NS.open({ rows, after_apply,
                                      title: __("Set Project — {0} orders from the sheet", [rows.length]) });
                        });
                },
            });
        };

        const esc = (s) => frappe.utils.escape_html(s == null ? "" : String(s));
        // Names can come from an uploaded sheet: build the link ourselves so
        // nothing in it is ever read as HTML.
        const link = (dt, name) => `<a href="/app/${frappe.router.slug(dt)}/${encodeURIComponent(name || "")}"
            target="_blank" rel="noopener">${esc(name)}</a>`;

        NS.render = function (res, applied) {
            const pn = (p) => esc((res.project_names || {})[p] || p || __("blank"));
            const t = res.totals;
            const counts = [t.orders, t.receipts, t.invoices, t.payments, t.journals];
            const trouble = t.unmatched || t.blocked_lines || res.skipped.length || res.conflicts.length;
            const head = applied
                ? `<div class="alert ${trouble ? "alert-warning" : "alert-success"}">${__(
                    "Done. {0} order(s), {1} GRN(s), {2} invoice(s), {3} payment(s) and {4} journal row(s) tagged.",
                    counts)}${trouble ? " " + __("Some items were left as they are — see below.") : ""}</div>`
                : `<div class="alert alert-info">${__(
                    "Will tag {0} order(s), {1} GRN(s), {2} invoice(s), {3} payment(s) and {4} journal row(s).",
                    counts)}</div>`;

            const status = {
                ready: applied ? __("Tagged") : __("Will be tagged"),
                partly: applied ? __("Tagged, some lines held back") : __("Some lines held back"),
                blocked: __("Held back — see below"),
                already: __("Already tagged — nothing to do"),
                duplicate: __("Listed again — counted once"),
            };
            const orders = res.orders.map((o) => `<tr>
                <td>${link("Purchase Order", o.purchase_order)}</td>
                <td>${esc(o.supplier)}</td>
                <td>${o.project ? pn(o.project) : esc(o.project_input)}</td>
                <td class="text-right">${o.lines || ""}</td>
                <td class="text-right">${o.receipts && o.receipts.length || ""}</td>
                <td class="text-right">${o.invoices && o.invoices.length || ""}</td>
                <td>${o.status === "error"
                    ? `<span class="text-danger">${esc(o.error)}</span>`
                    : esc(status[o.status] || o.status)}</td>
            </tr>`).join("");

            const ledger = {
                all: __("every ledger row"), match: __("ledger line by line"),
                stock: __("stock ledger, line by line"),
                unmatched: `<span class="text-warning">${__("ledger left as is — cannot be matched line by line")}</span>`,
                row: __("its ledger row"), none: "—",
            };
            const docs = res.documents.map((x) => `<tr>
                <td>${esc(__(x.kind))}</td>
                <td>${link(x.doctype, x.name)}${x.draft ? ` <span class="text-muted">(${__("draft")})</span>` : ""}</td>
                <td class="text-right">${x.lines || ""}${x.lines_total ? ` / ${x.lines_total}` : ""}${x.left_blank
                    ? ` <span class="text-muted">(${__("{0} without a project", [x.left_blank])})</span>` : ""}</td>
                <td>${x.header_from === x.header_to ? "" : `${pn(x.header_from)} → ${pn(x.header_to)}`}</td>
                <td>${ledger[x.ledger] || "—"}${x.ledger_rows != null ? ` (${esc(x.ledger_rows)})` : ""}</td>
            </tr>`).join("");

            const list = (title, items, fmt, cls) => items.length
                ? `<h6 class="mt-3 ${cls || ""}">${title} (${items.length})</h6><ul class="small">${
                    items.map((i) => `<li>${fmt(i)}</li>`).join("")}</ul>` : "";

            return `${head}
                <table class="table table-sm table-bordered small">
                  <thead><tr><th>${__("Purchase Order")}</th><th>${__("Supplier")}</th><th>${__("Project")}</th>
                  <th class="text-right">${__("PO lines")}</th><th class="text-right">${__("GRNs")}</th>
                  <th class="text-right">${__("Invoices")}</th><th>${__("Status")}</th></tr></thead>
                  <tbody>${orders}</tbody></table>
                ${list(__("Needs attention"), res.warnings,
                    (w) => `${link("Purchase Order", w.purchase_order)} — ${esc(w.message)}`, "text-warning")}
                ${list(__("Order lines held back, with everything made from them"), res.blocked,
                    (b) => `${link("Purchase Order", b.purchase_order)} ${__("line")} ${esc(b.line)} (${esc(b.item_code)}) — ${
                        b.reasons.map(esc).join("; ")}`, "text-warning")}
                ${list(__("Left as they are"), res.skipped,
                    (s) => `${link(s.doctype, s.name)} — ${esc(s.reason)}`)}
                ${list(__("Header kept on another project"), res.conflicts,
                    (c) => `${link(c.doctype, c.name)}: ${pn(c.has)} (${__("wanted")} ${pn(c.want)})`)}
                ${docs ? `<details class="mt-3"${applied ? " open" : ""}><summary>${__(
                    "Every document {0}", [applied ? __("changed") : __("that will change")])} (${res.documents.length})</summary>
                    <table class="table table-sm table-bordered small mt-2">
                    <thead><tr><th>${__("Type")}</th><th>${__("Document")}</th><th class="text-right">${__("Lines")}</th>
                    <th>${__("Header")}</th><th>${__("Ledger")}</th></tr></thead><tbody>${docs}</tbody></table></details>` : ""}`;
        };
    }

    if (!NS.__form) {
        NS.__form = true;
        frappe.ui.form.on("Purchase Order", {
            refresh(frm) {
                if (frm.doc.docstatus !== 1 || !NS.can()) return;
                frm.add_custom_button(__("Set Project"), () => NS.open({
                    rows: [{ purchase_order: frm.doc.name }], ask_project: true,
                    company: frm.doc.company, project: frm.doc.project,
                    title: __("Set Project — {0}", [frm.doc.name]),
                    after_apply: () => frm.reload_doc(),
                }), __("Project"));
            },
        });
    }

    const S = frappe.listview_settings && frappe.listview_settings["Purchase Order"];
    if (S && !S.__dux_project_tagging) {
        S.__dux_project_tagging = true;
        const prev = S.onload;
        S.onload = function (listview) {
            if (prev) prev.apply(this, arguments);
            if (!NS.can()) return;
            listview.page.add_actions_menu_item(__("Set Project"), () => {
                const names = listview.get_checked_items(true);
                if (!names.length) return frappe.msgprint(__("Tick the Purchase Orders first."));
                const cos = new Set(listview.get_checked_items().map((d) => d.company).filter(Boolean));
                NS.open({
                    rows: names.map((n) => ({ purchase_order: n })), ask_project: true,
                    company: cos.size === 1 ? [...cos][0] : null,
                    title: __("Set Project — {0} orders", [names.length]),
                    after_apply: () => listview.refresh(),
                });
            }, false);
            listview.page.add_menu_item(__("Set Project from Excel"),
                () => NS.upload(() => listview.refresh()));
        };
    }
})();
