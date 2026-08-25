// Payment Voucher - Client Script

let _party_dialog_open = false;

frappe.ui.form.on("Payment Voucher", {

    setup(frm) { },

    refresh(frm) {
        _apply_entry_mode(frm);
        _apply_payment_method_labels(frm);
        _set_paid_from_filter(frm);
        _set_cost_center_filter(frm);
        _set_project_filter(frm);
        _set_contra_filters(frm);
        _set_account_row_filter(frm);

        if (frm.doc.docstatus === 1 && !frm.doc.is_posted) {
            frm.reload_doc();
        }
    },

    after_save(frm) {
        frm.reload_doc();
    },

    before_save(frm) {
        if (frm.doc.entry_mode === "Head-wise" || frm.doc.entry_mode === "Party + Head Entry") {
            const rows = frm.doc.entry_mode === "Party + Head Entry" ? (frm.doc.combined_rows || []) : (frm.doc.account_rows || []);
            let total_debit = 0, total_credit = 0;
            rows.forEach(function (r) {
                total_debit += flt(r.debit);
                total_credit += flt(r.credit);
            });
            const net = total_debit - total_credit;
            const currency = frappe.boot.sysdefaults.currency || "INR";
            const paid_from = frm.doc.paid_from_account || "";

            if (net > 0) {
                frappe.show_alert({
                    message: __(
                        "Head-wise Payment Summary: Total Debit {0} | Total Credit {1} | Net amount of {2} will be credited to {3} on submission",
                        [
                            format_currency(total_debit, currency),
                            format_currency(total_credit, currency),
                            format_currency(net, currency),
                            paid_from
                        ]
                    ),
                    indicator: "blue"
                }, 8);
            }
        }
    },

    validate(frm) {
        // Guard: Party + Head Entry mode requires BOTH party rows AND head-only rows.
        // If all rows are parties OR all rows are heads, offer auto-conversion.
        if (frm.doc.entry_mode !== "Party + Head Entry") return;
        const rows = (frm.doc.combined_rows || []).filter(r => r.account);
        if (rows.length === 0) return;

        const with_party = rows.filter(r => r.party);
        const without_party = rows.filter(r => !r.party);

        if (with_party.length === rows.length || without_party.length === rows.length) {
            const target = with_party.length === rows.length ? "Party-wise" : "Head-wise";
            const kind = target === "Party-wise" ? "parties" : "account heads";

            frappe.validated = false;

            frappe.confirm(
                __('This is a "Party + Head Entry" voucher, but you have only entered {0}. Do you want to convert this into a {1} entry? Your row data will be preserved.', [kind, target]),
                () => setTimeout(() => _convert_combined_to(frm, target), 0),
                () => frappe.show_alert({
                    message: __("Save cancelled. Please add the missing {0}.",
                        [target === "Party-wise" ? "account-head rows" : "party rows"]),
                    indicator: "orange"
                }, 5)
            );
        }
    },

    entry_mode(frm) {
        _apply_entry_mode(frm);
        _apply_payment_method_labels(frm);
        _set_paid_from_filter(frm);
        if (!frm._auto_converting) {
            frm.set_value("paid_from_account", "");
            frm.set_value("amount", 0);
            frm.clear_table("party_rows");
            frm.clear_table("account_rows");
            frm.clear_table("combined_rows");
        }
        frm.refresh_fields();
    },

    mode_of_payment(frm) {
        _apply_payment_method_labels(frm);
        _set_paid_from_filter(frm);
        frm.set_value("paid_from_account", "");
    },

    company(frm) {
        _set_cost_center_filter(frm);
        _set_project_filter(frm);
        _set_contra_filters(frm);
        frm.set_value("paid_from_account", "");
        frm.set_value("cost_center", "");
        frm.set_value("project", "");
        frm.set_value("transfer_from_account", "");
        frm.set_value("transfer_to_account", "");
        _set_account_row_filter(frm);
    },

    amount(frm) {
        if (frm.doc.entry_mode === "Head-wise") {
            _headwise_autofill_on_amount_change(frm);
        }
    },

    paid_from_account(frm) {
        if (frm.doc.paid_from_account && frm.doc.company) {
            frappe.db.get_value("Account", frm.doc.paid_from_account, "company", (r) => {
                if (r && r.company !== frm.doc.company) {
                    frappe.show_alert({
                        message: __("Selected account does not belong to {0}", [frm.doc.company]),
                        indicator: "orange"
                    });
                    frm.set_value("paid_from_account", "");
                }
            });
        }
    },
});


frappe.ui.form.on("PV Party Row", {

    party(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.party) return;
        if (row._set_by_dialog) {
            row._set_by_dialog = false;
            return;
        }
        const typed = row.party;
        frappe.model.set_value(cdt, cdn, "party", "");
        // Clear stale balance when re-searching
        frappe.model.set_value(cdt, cdn, "current_balance", 0);
        frappe.model.set_value(cdt, cdn, "balance_type", "");
        _open_party_dialog(frm, cdt, cdn, typed);
    },

    amount(frm) {
        _sum_party_rows(frm);
    },

    party_rows_remove(frm) {
        _sum_party_rows(frm);
    },
});


frappe.ui.form.on("PV Account Row", {

    account_rows_add(frm, cdt, cdn) {
        _headwise_autofill_new_row(frm, cdt, cdn);
    },

    debit(frm, cdt, cdn) {
        _headwise_balance_next_row(frm, cdt, cdn);
        _show_headwise_totals(frm);
    },

    credit(frm, cdt, cdn) {
        _headwise_balance_next_row(frm, cdt, cdn);
        _show_headwise_totals(frm);
    },

    account_rows_remove(frm) {
        _show_headwise_totals(frm);
    },

    account(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.account) {
            // Account cleared — clear balance
            frappe.model.set_value(cdt, cdn, "current_balance", 0);
            frappe.model.set_value(cdt, cdn, "balance_type", "");
            return;
        }
        if (frm.doc.company) {
            frappe.db.get_value("Account", row.account, "company", (r) => {
                if (r && r.company !== frm.doc.company) {
                    frappe.model.set_value(cdt, cdn, "account", "");
                    frappe.model.set_value(cdt, cdn, "current_balance", 0);
                    frappe.model.set_value(cdt, cdn, "balance_type", "");
                    frappe.show_alert({
                        message: __("Account must belong to {0}", [frm.doc.company]),
                        indicator: "orange"
                    });
                } else {
                    // Account is valid — fetch its current balance
                    _fetch_account_balance(frm, cdt, cdn, row.account);
                }
            });
        }
    },
});


// ---------------------------------------------------------------
// Party search dialog
// ---------------------------------------------------------------

function _open_party_dialog(frm, cdt, cdn, prefill_txt) {
    if (_party_dialog_open) return;
    _party_dialog_open = true;

    const dialog = new frappe.ui.Dialog({
        title: __("Search Party"),
        fields: [
            {
                fieldname: "search_txt",
                fieldtype: "Data",
                label: __("Search Customer / Supplier / Employee"),
                placeholder: __("Type name to search..."),
            },
            {
                fieldname: "results_html",
                fieldtype: "HTML",
                options: '<div class="pv-party-results" style="max-height:360px;overflow-y:auto;margin-top:8px;"><div style="padding:16px;text-align:center;color:var(--color-text-secondary);font-size:13px;">Start typing to search...</div></div>'
            }
        ]
    });

    dialog.show();

    const $input = dialog.fields_dict.search_txt.$input;
    const $container = dialog.$wrapper.find(".pv-party-results");
    let _selected_idx = -1;
    let _current_results = [];
    let _is_keyboard_nav = false;

    const _highlight_row = function (idx) {
        $container.find(".pv-result-row").each(function (i) {
            if (i === idx) {
                $(this).css({
                    "background": "#e8e8e8",
                    "outline": "2px solid #888"
                });
            } else {
                $(this).css({
                    "background": "",
                    "outline": ""
                });
            }
        });
    };

    const _render = function (results) {
        _current_results = results;
        _selected_idx = -1;
        _is_keyboard_nav = false;
        $container.empty();

        if (!results.length) {
            $container.html('<div style="padding:16px;text-align:center;color:var(--color-text-secondary);font-size:13px;">No results found</div>');
            return;
        }

        const color_map = {
            "Customer": { bg: "#e6f1fb", color: "#185fa5" },
            "Supplier": { bg: "#eaf3de", color: "#3b6d11" },
            "Employee": { bg: "#faeeda", color: "#854f0b" }
        };

        results.forEach(function (r, idx) {
            const c = color_map[r.party_type] || { bg: "#f1efe8", color: "#5f5e5a" };
            const $row = $('<div class="pv-result-row" style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:0.5px solid var(--color-border-tertiary);cursor:pointer;transition:background 0.1s;"></div>');

            $row.append(
                $('<div></div>').append(
                    $('<div style="font-size:13px;font-weight:500;color:var(--color-text-primary);"></div>').text(r.name)
                ).append(
                    $('<div style="font-size:12px;margin-top:2px;color:var(--color-text-secondary);"></div>').text(r.display_name || "")
                )
            ).append(
                $('<span style="font-size:11px;padding:3px 10px;border-radius:20px;font-weight:500;white-space:nowrap;margin-left:12px;"></span>')
                    .css({ background: c.bg, color: c.color })
                    .text(r.party_type)
            );

            $row.on("mouseenter", function () {
                if (_is_keyboard_nav) return;
                _selected_idx = idx;
                _highlight_row(idx);
            });
            $row.on("mouseleave", function () {
                if (_is_keyboard_nav) return;
                $(this).css({ "background": "", "outline": "" });
                _selected_idx = -1;
            });
            $row.on("click", function () {
                _select_party(r);
            });

            $container.append($row);
        });
    };

    const _select_party = function (r) {
        const row = locals[cdt][cdn];
        row._set_by_dialog = true;
        frappe.model.set_value(cdt, cdn, "party", r.name);
        frappe.model.set_value(cdt, cdn, "party_type", r.party_type);
        frappe.model.set_value(cdt, cdn, "party_name", r.display_name);

        dialog.hide();
        frm.refresh_field("party_rows");

        setTimeout(function () {
            const grid = frm.fields_dict["party_rows"].grid;
            const $amount_input = grid.wrapper.find('.grid-row[data-name="' + cdn + '"] [data-fieldname="amount"] input');
            if ($amount_input.length) $amount_input.focus();
        }, 200);

        // Fetch and display current balance for selected party
        if (frm.doc.company) {
            frappe.call({
                method: "dux_voucher.dux_voucher.api.payment_voucher_api.get_party_balance",
                args: {
                    party_type: r.party_type,
                    party: r.name,
                    company: frm.doc.company,
                    posting_date: frm.doc.posting_date
                },
                callback: function (res) {
                    if (res.message) {
                        frappe.model.set_value(cdt, cdn, "current_balance", res.message.balance);
                        frappe.model.set_value(cdt, cdn, "balance_type", res.message.balance_type);
                        frm.refresh_field("party_rows");
                        // Show a quick alert so user notices the balance
                        if (res.message.balance_type !== "Nil") {
                            const currency = frappe.boot.sysdefaults.currency || "INR";
                            const indicator = res.message.balance_type === "Dr" ? "orange" : "blue";
                            frappe.show_alert({
                                message: __(
                                    "{0} current balance: {1} {2}",
                                    [r.name, format_currency(res.message.balance, currency), res.message.balance_type]
                                ),
                                indicator: indicator
                            }, 5);
                        }
                    }
                }
            });
        }
    };

    const _do_search = function (txt) {
        frappe.call({
            method: "dux_voucher.dux_voucher.api.payment_voucher_api.search_party",
            args: { doctype: "", txt: txt, searchfield: "name", start: 0, page_len: 20, filters: {} },
            callback: function (res) {
                if (res.message) {
                    _render(res.message.map(function (row) {
                        return { name: row[0], display_name: row[1], party_type: row[2] };
                    }));
                }
            }
        });
    };

    // Bind keydown directly on input — no document capture needed
    $input.on("keydown", function (e) {
        const rows = $container.find(".pv-result-row");
        if (!rows.length) return;

        if (e.which === 40) { // Arrow Down
            e.preventDefault();
            e.stopPropagation();
            _is_keyboard_nav = true;
            _selected_idx = Math.min(_selected_idx + 1, _current_results.length - 1);
            _highlight_row(_selected_idx);
            rows.eq(_selected_idx)[0].scrollIntoView({ block: "nearest" });

        } else if (e.which === 38) { // Arrow Up
            e.preventDefault();
            e.stopPropagation();
            _is_keyboard_nav = true;
            _selected_idx = Math.max(_selected_idx - 1, 0);
            _highlight_row(_selected_idx);
            rows.eq(_selected_idx)[0].scrollIntoView({ block: "nearest" });

        } else if (e.which === 13) { // Enter
            e.preventDefault();
            e.stopPropagation();
            if (_selected_idx >= 0 && _current_results[_selected_idx]) {
                _select_party(_current_results[_selected_idx]);
            }

        } else if (e.which === 27) { // Escape
            e.preventDefault();
            e.stopPropagation();
            dialog.hide();

        } else {
            // Any other key — reset keyboard nav
            _is_keyboard_nav = false;
        }
    });

    dialog.onhide = function () {
        _party_dialog_open = false;
    };

    setTimeout(function () {
        $input.focus();
        if (prefill_txt && prefill_txt.length > 0) {
            dialog.set_value("search_txt", prefill_txt);
            _do_search(prefill_txt);
        }
    }, 300);

    $input.on("input", frappe.utils.debounce(function () {
        const txt = $(this).val();
        if (txt.length < 1) {
            $container.html('<div style="padding:16px;text-align:center;color:var(--color-text-secondary);font-size:13px;">Start typing to search...</div>');
            _current_results = [];
            _selected_idx = -1;
            return;
        }
        _do_search(txt);
    }, 300));
}


// ---------------------------------------------------------------
// Balance fetching for account rows
// ---------------------------------------------------------------

function _fetch_account_balance(frm, cdt, cdn, account) {
    frappe.call({
        method: "dux_voucher.dux_voucher.api.payment_voucher_api.get_account_balance",
        args: {
            account: account,
            company: frm.doc.company,
            posting_date: frm.doc.posting_date
        },
        callback: function (res) {
            if (res.message) {
                frappe.model.set_value(cdt, cdn, "current_balance", res.message.balance);
                frappe.model.set_value(cdt, cdn, "balance_type", res.message.balance_type);
            }
        }
    });
}


// ---------------------------------------------------------------
// Entry mode helpers
// ---------------------------------------------------------------

function _apply_entry_mode(frm) {
    const mode = frm.doc.entry_mode;
    const is_combined = mode === "Party + Head Entry";

    frm.toggle_reqd("mode_of_payment", mode !== "Contra Entry");
    frm.toggle_reqd("paid_from_account", mode === "Party-wise" || mode === "Head-wise" || is_combined);
    frm.toggle_reqd("amount", mode === "Party-wise" || mode === "Contra Entry");
    frm.toggle_reqd("transfer_from_account", mode === "Contra Entry");
    frm.toggle_reqd("transfer_to_account", mode === "Contra Entry");

    frm.set_df_property("mode_of_payment", "hidden", mode === "Contra Entry" ? 1 : 0);
    frm.set_df_property("paid_from_account", "hidden", mode === "Contra Entry" ? 1 : 0);
    frm.set_df_property("amount", "hidden", 0);
    frm.set_df_property("amount", "read_only", (mode === "Head-wise" || is_combined) ? 1 : 0);
    frm.set_df_property("amount", "description",
        (mode === "Head-wise" || is_combined)
            ? __("Auto-calculated: Total Debit minus Total Credit from table")
            : ""
    );

    frm.refresh_fields();
}

function _apply_payment_method_labels(frm) {
    const mop = (frm.doc.mode_of_payment || "").toLowerCase();

    if (mop.includes("cheque") || mop.includes("check")) {
        frm.set_df_property("reference_no", "label", __("Cheque Number"));
        frm.set_df_property("reference_date", "label", __("Cheque Date"));
        frm.toggle_reqd("reference_no", true);
        frm.toggle_reqd("reference_date", true);
    } else if (mop.includes("neft") || mop.includes("rtgs") || mop.includes("upi") || mop.includes("imps") || mop.includes("bank")) {
        frm.set_df_property("reference_no", "label", __("UTR Number"));
        frm.set_df_property("reference_date", "label", __("Reference Date"));
        frm.toggle_reqd("reference_no", false);
        frm.toggle_reqd("reference_date", false);
    } else {
        frm.set_df_property("reference_no", "label", __("Reference No"));
        frm.set_df_property("reference_date", "label", __("Reference Date"));
        frm.toggle_reqd("reference_no", false);
        frm.toggle_reqd("reference_date", false);
    }

    frm.refresh_fields(["reference_no", "reference_date"]);
}

function _set_paid_from_filter(frm) {
    if (!frm.doc.mode_of_payment) {
        frm.set_query("paid_from_account", function () {
            return { filters: { company: frm.doc.company, account_type: ["in", ["Bank", "Cash"]], is_group: 0 } };
        });
        return;
    }
    frappe.call({
        method: "dux_voucher.dux_voucher.api.payment_voucher_api.get_mop_account_type",
        args: { mode_of_payment: frm.doc.mode_of_payment },
        callback: function (r) {
            const account_type = (r.message === "Cash") ? "Cash" : "Bank";
            frm.set_query("paid_from_account", function () {
                return { filters: { company: frm.doc.company, account_type: account_type, is_group: 0 } };
            });
        }
    });
}

function _set_contra_filters(frm) {
    frm.set_query("transfer_from_account", function () {
        return { filters: { company: frm.doc.company, account_type: ["in", ["Bank", "Cash"]], is_group: 0 } };
    });
    frm.set_query("transfer_to_account", function () {
        return { filters: { company: frm.doc.company, account_type: ["in", ["Bank", "Cash"]], is_group: 0 } };
    });
}

function _set_cost_center_filter(frm) {
    frm.set_query("cost_center", function () {
        return { filters: { company: frm.doc.company, is_group: 0 } };
    });
    frm.set_query("cost_center", "account_rows", function () {
        return { filters: { company: frm.doc.company, is_group: 0 } };
    });
}

function _set_project_filter(frm) {
    frm.set_query("project", function () {
        return { filters: { company: frm.doc.company } };
    });
    frm.set_query("project", "account_rows", function () {
        return { filters: { company: frm.doc.company } };
    });
}

function _sum_party_rows(frm) {
    let total = 0;
    (frm.doc.party_rows || []).forEach(function (r) { total += flt(r.amount); });

    const old_amount = flt(frm.doc.amount);
    if (Math.abs(old_amount - total) > 0.005 && total > 0) {
        frm.set_value("amount", total);
        const currency = frappe.boot.sysdefaults.currency || "INR";
        frappe.show_alert({
            message: __("Total payment amount updated to {0}", [format_currency(total, currency)]),
            indicator: "blue"
        }, 5);
    }
}

function _headwise_autofill_on_amount_change(frm) {
    const rows = frm.doc.account_rows || [];
    if (!rows.length) return;
    const first = rows[0];
    if (!flt(first.debit) && !flt(first.credit)) {
        frappe.model.set_value(first.doctype, first.name, "debit", flt(frm.doc.amount));
        _show_headwise_totals(frm);
    }
}

function _headwise_autofill_new_row(frm, cdt, cdn) {
    const amount = flt(frm.doc.amount);
    if (!amount) return;

    const rows = frm.doc.account_rows || [];
    let net_other = 0;
    rows.forEach(function (r) {
        if (r.name !== cdn) net_other += flt(r.debit) - flt(r.credit);
    });

    const remaining = amount - net_other;
    if (remaining > 0) {
        frappe.model.set_value(cdt, cdn, "debit", remaining);
        frappe.model.set_value(cdt, cdn, "credit", 0);
    } else if (remaining < 0) {
        frappe.model.set_value(cdt, cdn, "debit", 0);
        frappe.model.set_value(cdt, cdn, "credit", Math.abs(remaining));
    }
    _show_headwise_totals(frm);
}

function _headwise_balance_next_row(frm, cdt, cdn) {
    const amount = flt(frm.doc.amount);
    if (!amount) return;

    const rows = frm.doc.account_rows || [];
    const current_idx = rows.findIndex(function (r) { return r.name === cdn; });
    const next_row = rows[current_idx + 1];

    if (!next_row) {
        let total_debit = 0, total_credit = 0;
        rows.forEach(function (r) {
            total_debit += flt(r.debit);
            total_credit += flt(r.credit);
        });
        const net = total_debit - total_credit;
        if (net > 0) frm.set_value("amount", net);
        _show_headwise_totals(frm);
        return;
    }

    let net_except_next = 0;
    rows.forEach(function (r) {
        if (r.name !== next_row.name) net_except_next += flt(r.debit) - flt(r.credit);
    });

    const remaining = amount - net_except_next;
    if (remaining > 0) {
        frappe.model.set_value(next_row.doctype, next_row.name, "debit", remaining);
        frappe.model.set_value(next_row.doctype, next_row.name, "credit", 0);
    } else if (remaining < 0) {
        frappe.model.set_value(next_row.doctype, next_row.name, "debit", 0);
        frappe.model.set_value(next_row.doctype, next_row.name, "credit", Math.abs(remaining));
    } else {
        frappe.model.set_value(next_row.doctype, next_row.name, "debit", 0);
        frappe.model.set_value(next_row.doctype, next_row.name, "credit", 0);
    }
    _show_headwise_totals(frm);
}

function _show_headwise_totals(frm) {
    let total_debit = 0, total_credit = 0;
    (frm.doc.account_rows || []).forEach(function (r) {
        total_debit += flt(r.debit);
        total_credit += flt(r.credit);
    });

    const net = total_debit - total_credit;
    const currency = frappe.boot.sysdefaults.currency || "INR";
    const paid_from = frm.doc.paid_from_account || __("Bank/Cash Account");

    if (total_debit > 0 || total_credit > 0) {
        const color = Math.abs(net) < 0.005 ? "success" : net < 0 ? "danger" : "info";
        frm.dashboard.show_headline(
            '<span style="font-size:13px;">' +
            '<b>' + __("Debit") + ':</b> ' + format_currency(total_debit, currency) +
            ' &nbsp;|&nbsp; ' +
            '<b>' + __("Credit") + ':</b> ' + format_currency(total_credit, currency) +
            ' &nbsp;|&nbsp; ' +
            '<b>' + __("Auto credit to") + ' <i>' + paid_from + '</i>:</b> ' +
            '<span style="color:var(--color-text-' + color + ');">' +
            format_currency(net, currency) +
            '</span></span>'
        );
    } else {
        frm.dashboard.clear_headline();
    }
}

function _set_account_row_filter(frm) {
    frm.set_query("account", "account_rows", function () {
        return {
            filters: {
                company: frm.doc.company,
                is_group: 0
            }
        };
    });
    frm.set_query("account", "combined_rows", function () {
        return {
            filters: {
                company: frm.doc.company,
                is_group: 0
            }
        };
    });
    frm.set_query("cost_center", "combined_rows", function () {
        return { filters: { company: frm.doc.company, is_group: 0 } };
    });
    frm.set_query("project", "combined_rows", function () {
        return { filters: { company: frm.doc.company } };
    });
    frm.set_query("project", "party_rows", function () {
        return { filters: { company: frm.doc.company } };
    });
}


// ---------------------------------------------------------------
// PV Combined Row — event handlers
// ---------------------------------------------------------------

let _combined_party_dialog_open = false;

frappe.ui.form.on("PV Combined Row", {

    party(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.party) return;
        if (row._set_by_dialog) {
            row._set_by_dialog = false;
            return;
        }
        const typed = row.party;
        frappe.model.set_value(cdt, cdn, "party", "");
        frappe.model.set_value(cdt, cdn, "party_type", "");
        frappe.model.set_value(cdt, cdn, "party_name", "");
        frappe.model.set_value(cdt, cdn, "account", "");
        frappe.model.set_value(cdt, cdn, "current_balance", 0);
        frappe.model.set_value(cdt, cdn, "balance_type", "");
        _open_combined_party_dialog(frm, cdt, cdn, typed);
    },

    party_type(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.party_type) {
            // Party type cleared — clear party-related fields
            frappe.model.set_value(cdt, cdn, "party", "");
            frappe.model.set_value(cdt, cdn, "party_name", "");
            frappe.model.set_value(cdt, cdn, "account", "");
            frappe.model.set_value(cdt, cdn, "current_balance", 0);
            frappe.model.set_value(cdt, cdn, "balance_type", "");
        }
    },

    account(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.account) {
            frappe.model.set_value(cdt, cdn, "current_balance", 0);
            frappe.model.set_value(cdt, cdn, "balance_type", "");
            return;
        }
        if (frm.doc.company) {
            frappe.db.get_value("Account", row.account, "company", (r) => {
                if (r && r.company !== frm.doc.company) {
                    frappe.model.set_value(cdt, cdn, "account", "");
                    frappe.model.set_value(cdt, cdn, "current_balance", 0);
                    frappe.model.set_value(cdt, cdn, "balance_type", "");
                    frappe.show_alert({
                        message: __("Account must belong to {0}", [frm.doc.company]),
                        indicator: "orange"
                    });
                } else if (!row.party) {
                    // Only fetch account balance if no party (party balance is fetched separately)
                    _fetch_account_balance(frm, cdt, cdn, row.account);
                }
            });
        }
    },

    combined_rows_add(frm, cdt, cdn) {
        _combined_autofill_new_row(frm, cdt, cdn);
    },

    debit(frm, cdt, cdn) {
        _combined_balance_next_row(frm, cdt, cdn);
        _show_combined_totals(frm);
    },

    credit(frm, cdt, cdn) {
        _combined_balance_next_row(frm, cdt, cdn);
        _show_combined_totals(frm);
    },

    combined_rows_remove(frm) {
        _show_combined_totals(frm);
    },
});


// ---------------------------------------------------------------
// Combined party search dialog
// ---------------------------------------------------------------

function _open_combined_party_dialog(frm, cdt, cdn, prefill_txt) {
    if (_combined_party_dialog_open) return;
    _combined_party_dialog_open = true;

    const dialog = new frappe.ui.Dialog({
        title: __("Search Party"),
        fields: [
            {
                fieldname: "search_txt",
                fieldtype: "Data",
                label: __("Search Customer / Supplier / Employee"),
                placeholder: __("Type name to search..."),
            },
            {
                fieldname: "results_html",
                fieldtype: "HTML",
                options: '<div class="cb-party-results" style="max-height:360px;overflow-y:auto;margin-top:8px;"><div style="padding:16px;text-align:center;color:var(--color-text-secondary);font-size:13px;">Start typing to search...</div></div>'
            }
        ]
    });

    dialog.show();

    const $input = dialog.fields_dict.search_txt.$input;
    const $container = dialog.$wrapper.find(".cb-party-results");
    let _selected_idx = -1;
    let _current_results = [];
    let _is_keyboard_nav = false;

    const _highlight_row = function (idx) {
        $container.find(".cb-result-row").each(function (i) {
            if (i === idx) {
                $(this).css({ "background": "#e8e8e8", "outline": "2px solid #888" });
            } else {
                $(this).css({ "background": "", "outline": "" });
            }
        });
    };

    const _render = function (results) {
        _current_results = results;
        _selected_idx = -1;
        _is_keyboard_nav = false;
        $container.empty();

        if (!results.length) {
            $container.html('<div style="padding:16px;text-align:center;color:var(--color-text-secondary);font-size:13px;">No results found</div>');
            return;
        }

        const color_map = {
            "Customer": { bg: "#e6f1fb", color: "#185fa5" },
            "Supplier": { bg: "#eaf3de", color: "#3b6d11" },
            "Employee": { bg: "#faeeda", color: "#854f0b" }
        };

        results.forEach(function (r, idx) {
            const c = color_map[r.party_type] || { bg: "#f1efe8", color: "#5f5e5a" };
            const $row = $('<div class="cb-result-row" style="display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:0.5px solid var(--color-border-tertiary);cursor:pointer;transition:background 0.1s;"></div>');

            $row.append(
                $('<div></div>').append(
                    $('<div style="font-size:13px;font-weight:500;color:var(--color-text-primary);"></div>').text(r.name)
                ).append(
                    $('<div style="font-size:12px;margin-top:2px;color:var(--color-text-secondary);"></div>').text(r.display_name || "")
                )
            ).append(
                $('<span style="font-size:11px;padding:3px 10px;border-radius:20px;font-weight:500;white-space:nowrap;margin-left:12px;"></span>')
                    .css({ background: c.bg, color: c.color })
                    .text(r.party_type)
            );

            $row.on("mouseenter", function () {
                if (_is_keyboard_nav) return;
                _selected_idx = idx;
                _highlight_row(idx);
            });
            $row.on("mouseleave", function () {
                if (_is_keyboard_nav) return;
                $(this).css({ "background": "", "outline": "" });
                _selected_idx = -1;
            });
            $row.on("click", function () {
                _select_combined_party(r);
            });

            $container.append($row);
        });
    };

    const _select_combined_party = function (r) {
        const row = locals[cdt][cdn];
        row._set_by_dialog = true;
        frappe.model.set_value(cdt, cdn, "party", r.name);
        frappe.model.set_value(cdt, cdn, "party_type", r.party_type);
        frappe.model.set_value(cdt, cdn, "party_name", r.display_name);

        dialog.hide();
        frm.refresh_field("combined_rows");

        // Auto-resolve the party's default account
        if (frm.doc.company) {
            frappe.call({
                method: "dux_voucher.dux_voucher.api.payment_voucher_api.get_party_default_account",
                args: {
                    party_type: r.party_type,
                    party: r.name,
                    company: frm.doc.company
                },
                callback: function (res) {
                    if (res.message) {
                        frappe.model.set_value(cdt, cdn, "account", res.message);
                        frm.refresh_field("combined_rows");
                    }
                }
            });

            // Fetch party balance
            frappe.call({
                method: "dux_voucher.dux_voucher.api.payment_voucher_api.get_party_balance",
                args: {
                    party_type: r.party_type,
                    party: r.name,
                    company: frm.doc.company,
                    posting_date: frm.doc.posting_date
                },
                callback: function (res) {
                    if (res.message) {
                        frappe.model.set_value(cdt, cdn, "current_balance", res.message.balance);
                        frappe.model.set_value(cdt, cdn, "balance_type", res.message.balance_type);
                        frm.refresh_field("combined_rows");
                        if (res.message.balance_type !== "Nil") {
                            const currency = frappe.boot.sysdefaults.currency || "INR";
                            const indicator = res.message.balance_type === "Dr" ? "orange" : "blue";
                            frappe.show_alert({
                                message: __(
                                    "{0} current balance: {1} {2}",
                                    [r.name, format_currency(res.message.balance, currency), res.message.balance_type]
                                ),
                                indicator: indicator
                            }, 5);
                        }
                    }
                }
            });
        }

        // Focus the debit field after selection
        setTimeout(function () {
            const grid = frm.fields_dict["combined_rows"].grid;
            const $debit_input = grid.wrapper.find('.grid-row[data-name="' + cdn + '"] [data-fieldname="debit"] input');
            if ($debit_input.length) $debit_input.focus();
        }, 300);
    };

    const _do_search = function (txt) {
        frappe.call({
            method: "dux_voucher.dux_voucher.api.payment_voucher_api.search_party",
            args: { doctype: "", txt: txt, searchfield: "name", start: 0, page_len: 20, filters: {} },
            callback: function (res) {
                if (res.message) {
                    _render(res.message.map(function (row) {
                        return { name: row[0], display_name: row[1], party_type: row[2] };
                    }));
                }
            }
        });
    };

    $input.on("keydown", function (e) {
        const rows = $container.find(".cb-result-row");
        if (!rows.length) return;

        if (e.which === 40) {
            e.preventDefault(); e.stopPropagation();
            _is_keyboard_nav = true;
            _selected_idx = Math.min(_selected_idx + 1, _current_results.length - 1);
            _highlight_row(_selected_idx);
            rows.eq(_selected_idx)[0].scrollIntoView({ block: "nearest" });
        } else if (e.which === 38) {
            e.preventDefault(); e.stopPropagation();
            _is_keyboard_nav = true;
            _selected_idx = Math.max(_selected_idx - 1, 0);
            _highlight_row(_selected_idx);
            rows.eq(_selected_idx)[0].scrollIntoView({ block: "nearest" });
        } else if (e.which === 13) {
            e.preventDefault(); e.stopPropagation();
            if (_selected_idx >= 0 && _current_results[_selected_idx]) {
                _select_combined_party(_current_results[_selected_idx]);
            }
        } else if (e.which === 27) {
            e.preventDefault(); e.stopPropagation();
            dialog.hide();
        } else {
            _is_keyboard_nav = false;
        }
    });

    dialog.onhide = function () {
        _combined_party_dialog_open = false;
    };

    setTimeout(function () {
        $input.focus();
        if (prefill_txt && prefill_txt.length > 0) {
            dialog.set_value("search_txt", prefill_txt);
            _do_search(prefill_txt);
        }
    }, 300);

    $input.on("input", frappe.utils.debounce(function () {
        const txt = $(this).val();
        if (txt.length < 1) {
            $container.html('<div style="padding:16px;text-align:center;color:var(--color-text-secondary);font-size:13px;">Start typing to search...</div>');
            _current_results = [];
            _selected_idx = -1;
            return;
        }
        _do_search(txt);
    }, 300));
}


// ---------------------------------------------------------------
// Combined mode — auto-balance helpers
// ---------------------------------------------------------------

function _combined_autofill_new_row(frm, cdt, cdn) {
    const amount = flt(frm.doc.amount);
    if (!amount) return;

    const rows = frm.doc.combined_rows || [];
    let net_other = 0;
    rows.forEach(function (r) {
        if (r.name !== cdn) net_other += flt(r.debit) - flt(r.credit);
    });

    const remaining = amount - net_other;
    if (remaining > 0) {
        frappe.model.set_value(cdt, cdn, "debit", remaining);
        frappe.model.set_value(cdt, cdn, "credit", 0);
    } else if (remaining < 0) {
        frappe.model.set_value(cdt, cdn, "debit", 0);
        frappe.model.set_value(cdt, cdn, "credit", Math.abs(remaining));
    }
    _show_combined_totals(frm);
}

function _combined_balance_next_row(frm, cdt, cdn) {
    const amount = flt(frm.doc.amount);
    if (!amount) return;

    const rows = frm.doc.combined_rows || [];
    const current_idx = rows.findIndex(function (r) { return r.name === cdn; });
    const next_row = rows[current_idx + 1];

    if (!next_row) {
        let total_debit = 0, total_credit = 0;
        rows.forEach(function (r) {
            total_debit += flt(r.debit);
            total_credit += flt(r.credit);
        });
        const net = total_debit - total_credit;
        if (net > 0) frm.set_value("amount", net);
        _show_combined_totals(frm);
        return;
    }

    let net_except_next = 0;
    rows.forEach(function (r) {
        if (r.name !== next_row.name) net_except_next += flt(r.debit) - flt(r.credit);
    });

    const remaining = amount - net_except_next;
    if (remaining > 0) {
        frappe.model.set_value(next_row.doctype, next_row.name, "debit", remaining);
        frappe.model.set_value(next_row.doctype, next_row.name, "credit", 0);
    } else if (remaining < 0) {
        frappe.model.set_value(next_row.doctype, next_row.name, "debit", 0);
        frappe.model.set_value(next_row.doctype, next_row.name, "credit", Math.abs(remaining));
    } else {
        frappe.model.set_value(next_row.doctype, next_row.name, "debit", 0);
        frappe.model.set_value(next_row.doctype, next_row.name, "credit", 0);
    }
    _show_combined_totals(frm);
}

function _show_combined_totals(frm) {
    if (frm.doc.entry_mode !== "Party + Head Entry") return;

    let total_debit = 0, total_credit = 0;
    (frm.doc.combined_rows || []).forEach(function (r) {
        total_debit += flt(r.debit);
        total_credit += flt(r.credit);
    });

    const net = total_debit - total_credit;
    const currency = frappe.boot.sysdefaults.currency || "INR";
    const paid_from = frm.doc.paid_from_account || __("Bank/Cash Account");

    if (total_debit > 0 || total_credit > 0) {
        const color = Math.abs(net) < 0.005 ? "success" : net < 0 ? "danger" : "info";
        frm.dashboard.show_headline(
            '<span style="font-size:13px;">' +
            '<b>' + __("Debit") + ':</b> ' + format_currency(total_debit, currency) +
            ' &nbsp;|&nbsp; ' +
            '<b>' + __("Credit") + ':</b> ' + format_currency(total_credit, currency) +
            ' &nbsp;|&nbsp; ' +
            '<b>' + __("Auto credit to") + ' <i>' + paid_from + '</i>:</b> ' +
            '<span style="color:var(--color-text-' + color + ');">' +
            format_currency(net, currency) +
            '</span></span>'
        );
    } else {
        frm.dashboard.clear_headline();
    }
}


// ---------------------------------------------------------------
// Combined mode -> Party-wise / Head-wise auto-conversion
// ---------------------------------------------------------------

function _convert_combined_to(frm, target_mode) {
    // Snapshot rows before we modify anything
    const snapshot = (frm.doc.combined_rows || []).map(r => ({...r}));

    // Set the flag FIRST so any cascading handler respects it
    frm._auto_converting = true;

    // Clear combined and update entry_mode directly on the doc — bypassing
    // frm.set_value() avoids racing against the (async) entry_mode handler
    // which would otherwise wipe the tables we are about to populate.
    frm.clear_table("combined_rows");
    frm.doc.entry_mode = target_mode;

    // Populate the target child table BEFORE refreshing the form, so the
    // refresh renders the populated rows.
    if (target_mode === "Party-wise") {
        snapshot.forEach(r => {
            const net = flt(r.debit) - flt(r.credit);
            if (Math.abs(net) < 0.005) return;
            const row = frm.add_child("party_rows");
            row.party = r.party;
            row.party_type = r.party_type;
            row.party_name = r.party_name;
            row.amount = Math.abs(net);
            row.current_balance = r.current_balance;
            row.balance_type = r.balance_type;
        });
    } else if (target_mode === "Head-wise") {
        snapshot.forEach(r => {
            if (!flt(r.debit) && !flt(r.credit)) return;
            const row = frm.add_child("account_rows");
            row.account = r.account;
            row.debit = flt(r.debit);
            row.credit = flt(r.credit);
            row.cost_center = r.cost_center;
            row.project = r.project;
            row.current_balance = r.current_balance;
            row.balance_type = r.balance_type;
        });
    }

    // Manually invoke the UI helpers that the entry_mode handler would have
    // called — minus the destructive table-clearing it does for normal mode
    // switches.
    _apply_entry_mode(frm);
    _apply_payment_method_labels(frm);
    _set_paid_from_filter(frm);
    frm.refresh_field("entry_mode");
    frm.refresh_field("party_rows");
    frm.refresh_field("account_rows");
    frm.refresh_field("combined_rows");
    frm.refresh_fields();

    // Recompute header amount from the newly populated rows
    if (target_mode === "Party-wise") {
        _sum_party_rows(frm);
    } else if (target_mode === "Head-wise") {
        _show_headwise_totals(frm);
    }

    // Mark form dirty so the Save button stays enabled
    frm.dirty();

    frm._auto_converting = false;

    frappe.show_alert({
        message: __("Converted to {0} mode. Review the entries and click Save.", [target_mode]),
        indicator: "blue"
    }, 6);
}

// ---------------------------------------------------------------
// Header Project → blank party rows
//
// Party-wise posts one Payment Entry per row and each row carries its own
// Project, so a voucher paying five parties can tag only the two that
// belong to the project. Filling the header pushes it into rows that are
// still blank — visible in the grid, so what you see is what posts. Clear
// any row that does not belong.
// ---------------------------------------------------------------
frappe.ui.form.on("Payment Voucher", {
    project: function (frm) {
        if (!frm.doc.project) return;
        var touched = 0;
        (frm.doc.party_rows || []).forEach(function (row) {
            if (!row.project) {
                frappe.model.set_value(row.doctype, row.name, "project", frm.doc.project);
                touched++;
            }
        });
        if (touched) {
            frm.refresh_field("party_rows");
            frappe.show_alert({
                message: __("Project applied to {0} party row(s). Clear any that do not belong.", [touched]),
                indicator: "blue",
            }, 6);
        }
    },
});
