// Copyright (c) 2026, Dux Digitech and contributors
// For license information, please see license.txt

// Ex Student Opening Adjustment — type the CORRECT opening for each student;
// the voucher works out and posts only the difference. The server recomputes
// everything on save, so the figures here are a preview.

const EOA_API = 'dux_voucher.dux_voucher.api.ex_student_api.';

frappe.ui.form.on('Ex Student Opening Adjustment', {
    onload(frm) {
        frm._eoa_company = frm.doc.company;
        frm.set_query('ex_student', 'adjustments', () => ({
            filters: { company: frm.doc.company || '', is_disabled: 0 },
        }));
        if (frm.is_new() && !frm.doc.posting_date) {
            const first = (frm.doc.adjustments || [])[0];
            frappe.call({
                method: EOA_API + 'get_adjustment_defaults',
                args: { company: frm.doc.company, ex_student: first && first.ex_student },
            }).then((r) => {
                if (!r.message) return;
                if (!frm.doc.company && r.message.company) frm.set_value('company', r.message.company);
                frm.set_value('posting_date', r.message.posting_date);
            });
        }
    },

    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Import from CSV'), () => _eoa_csv_import(frm));
            frm.add_custom_button(__('Refresh Openings'), () => _eoa_refresh_openings(frm, true));
            // rows added from a student or a batch, and an amendment's copied
            // figures, are re-read before anyone relies on them
            const stale = (frm.doc.adjustments || []).some((r) => r.ex_student && !r.current_type);
            if (stale || (frm.is_new() && frm.doc.amended_from)) _eoa_refresh_openings(frm, false);
        }
        if (frm.doc.docstatus === 1 && frm.doc.backend_je) {
            frm.add_custom_button(__('View Journal Entry'),
                () => frappe.set_route('Form', 'Journal Entry', frm.doc.backend_je));
        }
        if (frm.doc.docstatus === 1) {
            frm.add_custom_button(__('Ex Student Outstanding'), () => {
                frappe.route_options = { company: frm.doc.company };
                frappe.set_route('query-report', 'Ex Student Outstanding');
            });
        }
        _eoa_headline(frm);
    },

    company(frm) {
        const rows = frm.doc.adjustments || [];
        const moved = frm._eoa_company && frm._eoa_company !== frm.doc.company;
        frm._eoa_company = frm.doc.company;
        if (moved && rows.some((r) => r.ex_student)) {
            frm.clear_table('adjustments');
            frm.refresh_field('adjustments');
            frappe.show_alert({ message: __('Students cleared: they belong to the previous company.'), indicator: 'orange' });
        }
        // a date set on purpose (from the batch, the student) stays; only a
        // change of company re-reads it
        if (frm.doc.company && (moved || !frm.doc.posting_date)) {
            frappe.call({ method: EOA_API + 'get_adjustment_defaults', args: { company: frm.doc.company } })
                .then((r) => r.message && frm.set_value('posting_date', r.message.posting_date));
        }
        _eoa_totals(frm);
    },

    adjustments_remove(frm) { _eoa_totals(frm); },
});

frappe.ui.form.on('Ex Student Opening Adjustment Row', {
    ex_student(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!row.ex_student) return;
        frappe.call({ method: EOA_API + 'get_opening_details', args: { ex_students: [row.ex_student] } })
            .then((r) => {
                const d = (r.message || {})[row.ex_student];
                if (!d) return;
                const vals = { student_name: d.student_name, current_amount: d.amount, current_type: d.type };
                if (_eoa_blank(row.correct_amount)) {
                    // start from the figure as it stands, on its own side:
                    // nothing changes until the clerk types the right one
                    vals.correct_amount = d.amount;
                    vals.correct_type = d.type === 'Cr' ? 'Cr' : 'Dr';
                }
                frappe.model.set_value(cdt, cdn, vals).then(() => _eoa_row(frm, cdt, cdn));
            });
    },
    correct_amount(frm, cdt, cdn) { _eoa_row(frm, cdt, cdn); },
    correct_type(frm, cdt, cdn) { _eoa_row(frm, cdt, cdn); },
});

function _eoa_blank(v) {
    return v === null || v === undefined || v === '';
}

function _eoa_signed(amount, dr_cr) {
    const a = Math.abs(flt(amount));
    return dr_cr === 'Cr' ? -a : a;
}

function _eoa_diff(row) {
    // a blank Correct Opening is not "nil": no change until it is filled
    if (_eoa_blank(row.correct_amount) || !row.current_type) return 0;
    return flt(_eoa_signed(row.correct_amount, row.correct_type || 'Dr')
               - _eoa_signed(row.current_amount, row.current_type), 2);
}

function _eoa_change(diff) {
    if (diff > 0) return format_currency(diff) + ' Dr';
    if (diff < 0) return format_currency(-diff) + ' Cr';
    return '';
}

function _eoa_row(frm, cdt, cdn) {
    const diff = _eoa_diff(locals[cdt][cdn]);
    frappe.model.set_value(cdt, cdn, {
        debit: diff > 0 ? diff : 0, credit: diff < 0 ? -diff : 0, change: _eoa_change(diff),
    });
    _eoa_totals(frm);
}

function _eoa_totals(frm) {
    let td = 0, tc = 0;
    (frm.doc.adjustments || []).forEach((r) => { td += flt(r.debit); tc += flt(r.credit); });
    frm.doc.total_debit = td;
    frm.doc.total_credit = tc;
    frm.doc.net_amount = flt(td - tc, 2);
    frm.refresh_fields(['total_debit', 'total_credit', 'net_amount']);
    _eoa_headline(frm);
}

function _eoa_headline(frm) {
    // Frappe 16 appends a new bar on every set_headline: clear first.
    frm.dashboard.clear_headline();
    if (frm.doc.docstatus === 2) {
        frm.dashboard.set_headline(__('Cancelled: everything this correction posted has been reversed.'), 'red');
        return;
    }
    const rows = (frm.doc.adjustments || []).filter((r) => r.ex_student);
    if (!rows.length) return;
    const td = flt(frm.doc.total_debit), tc = flt(frm.doc.total_credit), net = td - tc;
    const parts = [__('{0} student(s)', [rows.length])];
    if (td > 0) parts.push(__('raise {0}', [format_currency(td)]));
    if (tc > 0) parts.push(__('reduce {0}', [format_currency(tc)]));
    let net_label;
    if (Math.abs(net) < 0.005) net_label = __('net nil: no journal entry, the money only moves between students');
    else if (net > 0) net_label = __('posts {0} Dr to Ex-Students Receivable', [format_currency(net)]);
    else net_label = __('posts {0} Cr to Ex-Students Receivable', [format_currency(-net)]);
    frm.dashboard.set_headline(parts.join('  ·  ') + '  →  ' + net_label,
                               frm.doc.docstatus === 1 ? 'green' : 'blue');
}

function _eoa_refresh_openings(frm, announce) {
    const rows = (frm.doc.adjustments || []).filter((r) => r.ex_student);
    if (!rows.length) return;
    frappe.call({
        method: EOA_API + 'get_opening_details',
        args: { ex_students: rows.map((r) => r.ex_student) },
    }).then((r) => {
        const d = r.message || {};
        let changed = false;
        rows.forEach((row) => {
            const o = d[row.ex_student];
            if (!o) return;
            frappe.utils.add_link_title('Ex Student', row.ex_student, o.student_name);
            if (row.current_amount !== o.amount || row.current_type !== o.type) changed = true;
            row.student_name = o.student_name;
            row.current_amount = o.amount;
            row.current_type = o.type;
            if (_eoa_blank(row.correct_amount)) {
                row.correct_amount = o.amount;
                row.correct_type = o.type === 'Cr' ? 'Cr' : 'Dr';
            }
            const diff = _eoa_diff(row);
            row.debit = diff > 0 ? diff : 0;
            row.credit = diff < 0 ? -diff : 0;
            row.change = _eoa_change(diff);
        });
        frm.refresh_field('adjustments');
        _eoa_totals(frm);
        // let Save run with the new figures (a clean form will not save)
        if (changed && !frm.is_new() && frm.doc.docstatus === 0) frm.dirty();
        if (announce) {
            frappe.show_alert({
                message: changed ? __('Current openings refreshed: check the changes, then save')
                                 : __('Current openings are up to date'),
                indicator: changed ? 'orange' : 'green',
            });
        }
    });
}

function _eoa_csv_import(frm) {
    if (!frm.doc.company) {
        frappe.msgprint({ title: __('Set Company'), message: __('Set the Company before importing.'), indicator: 'orange' });
        return;
    }
    if (!(frm.doc.reason || '').trim()) {
        frappe.msgprint({ title: __('Give a Reason'), message: __('Fill in the Reason first: the draft is saved before the import.'), indicator: 'orange' });
        return;
    }
    const ensure_saved = (frm.is_new() || frm.is_dirty()) ? frm.save() : Promise.resolve();
    ensure_saved.then(() => {
        // frm.save() resolves even when the server refused it
        if (frm.is_new() || frm.is_dirty()) return;
        const help_html =
            '<div class="text-muted" style="margin-bottom:8px">' +
            '<p>' + __('One row per student whose opening is wrong, with the <b>correct</b> opening.') + '</p>' +
            '<p><b>' + __('Columns (first row = header):') + '</b><br>' +
            '<code>ex_student</code> ' + __('or') + ' <code>student_id</code> ' + __('or') + ' <code>student_name</code>; ' +
            '<code>debit</code> ' + __('(student owes) or') + ' <code>credit</code> ' + __('(advance)') + '; <code>remarks</code>.</p>' +
            '<p>' + __('Put 0 in debit to make an opening nil. Students whose opening is already right are skipped; nobody new is created.') + '</p>' +
            '<p><a href="#" class="eoa-template"><i class="fa fa-download"></i> ' + __('Download template CSV') + '</a></p>' +
            '</div>';
        const d = new frappe.ui.Dialog({
            title: __('Import Corrections from CSV'),
            fields: [
                { fieldtype: 'HTML', fieldname: 'help', options: help_html },
                { label: __('CSV File'), fieldname: 'csv_file', fieldtype: 'Attach', reqd: 1 },
            ],
            primary_action_label: __('Import'),
            primary_action(values) {
                frappe.call({
                    method: EOA_API + 'import_adjustments_csv',
                    args: { adjustment: frm.doc.name, file_url: values.csv_file },
                    freeze: true,
                    freeze_message: __('Reading corrections...'),
                }).then((r) => {
                    if (!r.message) return;
                    d.hide();
                    frm.reload_doc();
                    const { added, unchanged, errors } = r.message;
                    let msg = __('{0} student(s) added.', [added]);
                    if (unchanged) msg += ' ' + __('{0} already had the right opening and were skipped.', [unchanged]);
                    if (errors && errors.length) {
                        msg += '<br><br><b>' + __('Not imported:') + '</b><ul>' +
                               errors.map((e) => '<li>' + frappe.utils.escape_html(e) + '</li>').join('') + '</ul>';
                    }
                    frappe.msgprint({ title: __('CSV Import'), message: msg, indicator: errors && errors.length ? 'orange' : 'green' });
                });
            },
        });
        d.show();
        d.$wrapper.find('.eoa-template').on('click', (e) => {
            e.preventDefault();
            const csv = 'ex_student,student_id,student_name,debit,credit,remarks\n' +
                        'EX-STU-00012,,,15000,,typed 51000 instead of 15000\n' +
                        ',STU-002,,,2500,advance was not entered\n' +
                        ',,Ramesh Sharma,0,,fees were cleared before migration\n';
            const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'ex_student_opening_corrections.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        });
    });
}
