/* ============================================================
   Student Journal Voucher — form behaviour
   Dux Digitech · dux_voucher

   One student per voucher. The form keeps three things in view
   before anything posts:
     * the student's current balance (from the ledger) and what it
       becomes after this voucher;
     * a Tally-style preview of every Dr / Cr line that will post —
       including the receiving institute's own entry on a transfer;
     * pickers narrowed to what the purpose allows (no Bank/Cash,
       no Receivable/Payable, root types per purpose), so a wrong
       ledger is hard to pick in the first place. The server checks
       all of it again.
   ============================================================ */

const SJV_TRANSFER = ["Transfer to Institute", "Transfer to Another Student"];
const SJV_CREDIT = ["Concession", "Other Credit to Student"];
const SJV_ROOT_TYPES = {
    "Fee Charged": ["Income", "Liability"],
    "Fine / Penalty": ["Income"],
    "Concession": ["Income", "Expense"],
};
const SJV_BLOCKED = ["Bank", "Cash", "Receivable", "Payable"];
// With a root-type filter in place Bank/Cash assets are already excluded,
// and income heads the chart types "Cash" (Student ID Card Fine …) must
// stay pickable — so only the party types are filtered out then.
const SJV_PARTY_TYPES = ["Receivable", "Payable"];

frappe.ui.form.on("Student Journal Voucher", {
    setup(frm) {
        frm.set_query("student", () => ({
            filters: { company: frm.doc.company || "__none__", is_disabled: 0 },
        }));
        frm.set_query("to_student", () => {
            const filters = { is_disabled: 0, name: ["!=", frm.doc.student || ""] };
            filters.company = frm.doc.purpose === "Transfer to Institute"
                ? (frm.doc.to_company || "__none__")
                : (frm.doc.company || "__none__");
            return { filters };
        });
        frm.set_query("to_company", () => ({
            filters: { is_group: 0, name: ["!=", frm.doc.company || ""] },
        }));
        frm.set_query("to_account", () => ({
            filters: {
                company: frm.doc.to_company || "__none__",
                is_group: 0, disabled: 0,
                account_type: ["not in", SJV_BLOCKED],
                root_type: ["in", ["Asset", "Liability"]],
            },
        }));
        frm.set_query("account", "heads", () => {
            const roots = SJV_ROOT_TYPES[frm.doc.purpose];
            const filters = {
                company: frm.doc.company || "__none__",
                is_group: 0, disabled: 0,
                account_type: ["not in", roots ? SJV_PARTY_TYPES : SJV_BLOCKED],
            };
            if (roots) filters.root_type = ["in", roots];
            if (frm._sjv && frm._sjv.account) filters.name = ["!=", frm._sjv.account];
            return { filters };
        });
    },

    refresh(frm) {
        if (frm.doc.docstatus === 1) {
            if (frm.doc.backend_je) {
                frm.add_custom_button(__("Journal Entry"), () =>
                    frappe.set_route("Form", "Journal Entry", frm.doc.backend_je), __("Open"));
            }
            if (frm.doc.to_company_je) {
                frm.add_custom_button(__("Institute Journal Entry"), () =>
                    frappe.set_route("Form", "Journal Entry", frm.doc.to_company_je), __("Open"));
            }
        }
        if (frm.doc.student && frm.doc.company) {
            frm.add_custom_button(__("Student Ledger"), () => {
                frappe.route_options = {
                    company: frm.doc.company, kind: "new", student: frm.doc.student,
                    student_label: frm.doc.student_name,
                };
                frappe.set_route("dux-student-ledger");
            }, __("Open"));
        }
        _sjv_load(frm);
    },

    company(frm) {
        if (frm.doc.docstatus !== 0) return;
        frm.set_value("student", null);
        frm.set_value("to_student", null);
        frm.set_value("to_company", null);
        if ((frm.doc.heads || []).length) {
            // Ledgers belong to the old company — they cannot carry over.
            frm.clear_table("heads");
            frm.refresh_field("heads");
        }
        _sjv_load(frm);
    },

    purpose(frm) {
        if (frm.doc.docstatus !== 0) return;
        if (!SJV_TRANSFER.includes(frm.doc.purpose)) {
            frm.set_value({ to_company: null, to_account: null, to_student: null, amount: 0 });
        } else {
            if (frm.doc.heads && frm.doc.heads.length) {
                frm.clear_table("heads");
                frm.refresh_field("heads");
            }
            frm.set_value("to_student", null);
            _sjv_default_amount(frm);
        }
        _sjv_toggle_to_student(frm);
        _sjv_render(frm);
    },

    student(frm) {
        if (frm.doc.docstatus !== 0) return;
        frm.set_value("amount", 0);
        _sjv_load(frm);
    },

    to_company(frm) {
        if (frm.doc.docstatus !== 0) return;
        frm.set_value({ to_account: null, to_student: null });
        _sjv_load(frm);
    },

    to_account(frm) { _sjv_toggle_to_student(frm); _sjv_render(frm); },
    to_student(frm) { _sjv_render(frm); },
    amount(frm) { _sjv_render(frm); },
    heads_remove(frm) { _sjv_render(frm); },
});

frappe.ui.form.on("Student Journal Voucher Head", {
    account(frm) { _sjv_render(frm); },
    amount(frm) { _sjv_render(frm); },
});


/* ── Server context: student account, balance, transfer accounts ── */
function _sjv_load(frm) {
    if (!frm.doc.company) { frm._sjv = null; _sjv_render(frm); return; }
    frappe.call({
        method: "dux_voucher.dux_voucher.doctype.student_journal_voucher.student_journal_voucher.get_context",
        args: { company: frm.doc.company, student: frm.doc.student, to_company: frm.doc.to_company },
        callback: (r) => {
            frm._sjv = r.message || {};
            if (frm.doc.docstatus === 0 && frm.doc.purpose === "Transfer to Institute") {
                if (!frm.doc.to_account && frm._sjv.to_account_default) {
                    frm.set_value("to_account", frm._sjv.to_account_default);
                }
                frm.set_value("from_branch_account", frm._sjv.from_branch_account || null);
                frm.set_value("to_branch_account", frm._sjv.to_branch_account || null);
            }
            _sjv_default_amount(frm);
            _sjv_toggle_to_student(frm);
            _sjv_render(frm);
        },
    });
}

function _sjv_default_amount(frm) {
    if (frm.doc.docstatus !== 0 || !SJV_TRANSFER.includes(frm.doc.purpose)) return;
    const bal = frm._sjv ? flt(frm._sjv.balance) : 0;
    if (!flt(frm.doc.amount) && bal > 0) frm.set_value("amount", bal);
}

function _sjv_toggle_to_student(frm) {
    // On a transfer to an institute the receiving student is only needed
    // when the institute's own student ledger is the one credited.
    if (frm.doc.purpose !== "Transfer to Institute") {
        frm.toggle_display("to_student", true);
        frm.toggle_reqd("to_student", frm.doc.purpose === "Transfer to Another Student");
        return;
    }
    const need = frm._sjv && frm.doc.to_account
        && frm.doc.to_account === frm._sjv.to_control_account;
    frm.toggle_display("to_student", !!need);
    frm.toggle_reqd("to_student", !!need);
    if (!need && frm.doc.to_student && frm.doc.docstatus === 0) frm.set_value("to_student", null);
}


/* ── Balance + entry preview ─────────────────────────────────────── */
function _sjv_money(v) { return format_currency(Math.abs(flt(v)), frappe.defaults.get_default("currency") || "INR"); }

function _sjv_bal_text(v) {
    v = flt(v);
    if (Math.abs(v) < 0.005) return `<span style="color:#64748b">Nil</span>`;
    return v > 0
        ? `<span style="color:#047857;font-weight:600">${_sjv_money(v)} Cr</span> <span style="color:#64748b">held for the student</span>`
        : `<span style="color:#b91c1c;font-weight:600">${_sjv_money(v)} Dr</span> <span style="color:#64748b">the student owes</span>`;
}

function _sjv_total(frm) {
    if (SJV_TRANSFER.includes(frm.doc.purpose)) return flt(frm.doc.amount);
    return (frm.doc.heads || []).reduce((s, r) => s + flt(r.amount), 0);
}

function _sjv_render(frm) {
    const ctx = frm._sjv || {};
    const bal_wrap = frm.get_field("balance_html").$wrapper;
    const prev_wrap = frm.get_field("preview_html").$wrapper;

    if (ctx.migrated === false) {
        bal_wrap.html(`<div style="padding:8px 10px;border-radius:6px;background:#fff7ed;color:#9a3412;font-size:12px">
            The student ledger has not been set up on this site yet — vouchers cannot be posted until a System Manager runs the migration.</div>`);
        prev_wrap.empty();
        return;
    }

    // Balance block
    if (frm.doc.docstatus === 0 && frm.doc.student && ctx.balance !== undefined && ctx.balance !== null) {
        const total = _sjv_total(frm);
        const sign = SJV_CREDIT.includes(frm.doc.purpose) ? 1 : -1;
        const after = flt(ctx.balance) + sign * total;
        bal_wrap.html(`<div style="font-size:12px;line-height:1.9;padding:2px 0">
            <div>Balance now: ${_sjv_bal_text(ctx.balance)}</div>
            ${frm.doc.purpose && total ? `<div>After this voucher: ${_sjv_bal_text(after)}</div>` : ""}
        </div>`);
    } else if (frm.doc.docstatus > 0) {
        bal_wrap.html(`<div style="font-size:12px;line-height:1.9;padding:2px 0">
            <div>Before: ${_sjv_bal_text(frm.doc.balance_before)}</div>
            <div>After: ${_sjv_bal_text(frm.doc.balance_after)}</div></div>`);
    } else {
        bal_wrap.empty();
    }

    // Entry preview
    const lines = _sjv_lines(frm, ctx);
    if (!lines.main.length) { prev_wrap.empty(); return; }
    const table = (title, rows) => {
        const dr = rows.reduce((s, l) => s + (l.side === "Dr" ? l.amount : 0), 0);
        const cr = rows.reduce((s, l) => s + (l.side === "Cr" ? l.amount : 0), 0);
        return `<div style="font-size:10.5px;text-transform:uppercase;letter-spacing:.5px;color:#64748b;margin:8px 0 4px">${frappe.utils.escape_html(title)}</div>
        <table style="width:100%;border-collapse:collapse;font-size:12px">
          <tr style="color:#64748b;border-bottom:1px solid #e2e8f0"><th style="text-align:left;padding:4px 6px">Ledger</th>
            <th style="text-align:right;padding:4px 6px;width:120px">Debit</th><th style="text-align:right;padding:4px 6px;width:120px">Credit</th></tr>
          ${rows.map(l => `<tr style="border-bottom:1px solid #f1f5f9">
            <td style="padding:4px 6px">${frappe.utils.escape_html(l.account || "—")}${l.party ? ` <span style="color:#6d28d9">· ${frappe.utils.escape_html(l.party)}</span>` : ""}</td>
            <td style="text-align:right;padding:4px 6px">${l.side === "Dr" ? _sjv_money(l.amount) : ""}</td>
            <td style="text-align:right;padding:4px 6px">${l.side === "Cr" ? _sjv_money(l.amount) : ""}</td></tr>`).join("")}
          <tr style="font-weight:600"><td style="padding:4px 6px">Total</td>
            <td style="text-align:right;padding:4px 6px">${_sjv_money(dr)}</td><td style="text-align:right;padding:4px 6px">${_sjv_money(cr)}</td></tr>
        </table>`;
    };
    let html = table(frm.doc.docstatus === 1 ? __("Posted in {0}", [frm.doc.company]) : __("Will post in {0}", [frm.doc.company || ""]), lines.main);
    if (lines.inst.length) {
        html += table(frm.doc.docstatus === 1 ? __("Posted in {0}", [frm.doc.to_company]) : __("Will post in {0}", [frm.doc.to_company]), lines.inst);
    }
    if (ctx.branch_error && frm.doc.purpose === "Transfer to Institute" && frm.doc.docstatus === 0) {
        html += `<div style="margin-top:8px;padding:6px 8px;border-radius:6px;background:#fef2f2;color:#991b1b;font-size:12px">${ctx.branch_error}</div>`;
    }
    prev_wrap.html(html);
}

function _sjv_lines(frm, ctx) {
    const main = [], inst = [];
    const total = _sjv_total(frm);
    const acct = ctx.account || __("Student ledger");
    const who = frm.doc.student_name || frm.doc.student;
    if (!frm.doc.purpose || !frm.doc.student || !total) return { main, inst };
    const sside = SJV_CREDIT.includes(frm.doc.purpose) ? "Cr" : "Dr";
    const other = sside === "Dr" ? "Cr" : "Dr";
    main.push({ account: acct, party: who, side: sside, amount: total });
    if (frm.doc.purpose === "Transfer to Institute") {
        const from_b = frm.doc.from_branch_account || ctx.from_branch_account;
        const to_b = frm.doc.to_branch_account || ctx.to_branch_account;
        main.push({ account: from_b, side: "Cr", amount: total });
        if (frm.doc.to_company) {
            inst.push({ account: to_b, side: "Dr", amount: total });
            inst.push({ account: frm.doc.to_account, party: frm.doc.to_student ? (frm.doc.to_student_name || frm.doc.to_student) : "", side: "Cr", amount: total });
        }
    } else if (frm.doc.purpose === "Transfer to Another Student") {
        main.push({ account: acct, party: frm.doc.to_student_name || frm.doc.to_student, side: "Cr", amount: total });
    } else {
        (frm.doc.heads || []).forEach(r => {
            if (r.account && flt(r.amount)) main.push({ account: r.account, side: other, amount: flt(r.amount) });
        });
    }
    return { main, inst };
}
