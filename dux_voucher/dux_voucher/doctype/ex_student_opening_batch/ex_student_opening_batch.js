// Copyright (c) 2026, Dux Digitech and contributors
// For license information, please see license.txt

frappe.ui.form.on('Ex Student Opening Batch', {
    refresh(frm) {
        if (frm.doc.docstatus === 0) {
            frm.add_custom_button(__('Import from CSV'), () => _open_csv_import(frm));
        }
        if (frm.doc.docstatus === 1 && frm.doc.backend_je) {
            frm.add_custom_button(
                __('View Journal Entry'),
                () => frappe.set_route('Form', 'Journal Entry', frm.doc.backend_je)
            );
        }
        _show_totals_headline(frm);
    },

    company(frm) {
        frm.set_query('ex_student', 'students_table', () => ({
            filters: { company: frm.doc.company || '', is_disabled: 0 },
        }));
    },

    onload(frm) {
        frm.set_query('ex_student', 'students_table', () => ({
            filters: { company: frm.doc.company || '', is_disabled: 0 },
        }));
    },

    students_table_add(frm)    { _recompute_totals(frm); },
    students_table_remove(frm) { _recompute_totals(frm); },
});

frappe.ui.form.on('Ex Student Opening Row', {
    debit_amount(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (flt(row.debit_amount) > 0 && flt(row.credit_amount) > 0) {
            row.credit_amount = 0;
            frm.refresh_field('students_table');
        }
        _recompute_totals(frm);
    },
    credit_amount(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (flt(row.credit_amount) > 0 && flt(row.debit_amount) > 0) {
            row.debit_amount = 0;
            frm.refresh_field('students_table');
        }
        _recompute_totals(frm);
    },
    ex_student(frm) { _recompute_totals(frm); },
});

function _recompute_totals(frm) {
    let td = 0, tc = 0;
    (frm.doc.students_table || []).forEach(r => {
        td += flt(r.debit_amount);
        tc += flt(r.credit_amount);
    });
    frm.set_value('total_debit', td);
    frm.set_value('total_credit', tc);
    frm.set_value('net_amount', td - tc);
    _show_totals_headline(frm);
}

function _show_totals_headline(frm) {
    const td = flt(frm.doc.total_debit);
    const tc = flt(frm.doc.total_credit);
    const net = td - tc;
    if (td === 0 && tc === 0) {
        frm.dashboard.clear_headline();
        return;
    }
    const parts = [];
    if (td > 0) parts.push(__('Dr {0}', [format_currency(td)]));
    if (tc > 0) parts.push(__('Cr {0}', [format_currency(tc)]));
    let net_label;
    if (Math.abs(net) < 0.005) {
        net_label = __('Net Nil');
    } else if (net > 0) {
        net_label = __('Net {0} Dr', [format_currency(net)]);
    } else {
        net_label = __('Net {0} Cr', [format_currency(Math.abs(net))]);
    }
    frm.dashboard.set_headline(parts.join('  &bull;  ') + '  &raquo;  ' + net_label, 'blue');
}

function _open_csv_import(frm) {
    if (!frm.doc.company) {
        frappe.msgprint({
            title: __('Set Company'),
            message: __('Please set the Company before importing.'),
            indicator: 'orange',
        });
        return;
    }
    const ensure_saved = (frm.is_new() || frm.is_dirty()) ? frm.save() : Promise.resolve();
    ensure_saved.then(() => {
        const company_esc = frappe.utils.escape_html(frm.doc.company);
        const help_html =
            '<div class="text-muted" style="margin-bottom:8px">' +
            '<p><b>Expected columns (first row = header):</b><br>' +
            '<code>student_name</code>, <code>debit</code>, <code>credit</code>, ' +
            '<code>student_id</code>, <code>father_name</code>, <code>course</code>, ' +
            '<code>batch_year</code>, <code>admission_session</code>, ' +
            '<code>mobile</code>, <code>email</code>, <code>remarks</code>.</p>' +
            '<p>Each row: fill <b>debit</b> if the student owes you, or <b>credit</b> if it is an advance. ' +
            'Only one of them per row.</p>' +
            '<p>Students not yet in <b>' + company_esc + '</b> will be auto-created.</p>' +
            '<p><a href="#" class="dv-download-template"><i class="fa fa-download"></i> Download template CSV</a></p>' +
            '</div>';

        const d = new frappe.ui.Dialog({
            title: __('Import Students from CSV'),
            fields: [
                { fieldtype: 'HTML', fieldname: 'help', options: help_html },
                { label: __('CSV File'), fieldname: 'csv_file', fieldtype: 'Attach', reqd: 1 },
            ],
            primary_action_label: __('Import'),
            primary_action(values) {
                frappe.call({
                    method: 'dux_voucher.dux_voucher.api.ex_student_api.import_from_csv',
                    args: { batch_name: frm.doc.name, file_url: values.csv_file },
                    freeze: true,
                    freeze_message: __('Importing students...'),
                    callback: (r) => {
                        if (!r.message) return;
                        d.hide();
                        const { created, appended, errors } = r.message;
                        frm.reload_doc();
                        let msg = __('Imported {0} rows. {1} new student(s) auto-created.', [appended, created]);
                        if (errors && errors.length) {
                            msg += '<br><br><b>' + __('Errors:') + '</b><ul>' +
                                   errors.map(e => '<li>' + frappe.utils.escape_html(e) + '</li>').join('') +
                                   '</ul>';
                        }
                        frappe.msgprint({
                            title: __('CSV Import'),
                            message: msg,
                            indicator: errors && errors.length ? 'orange' : 'green',
                        });
                    },
                });
            },
        });
        d.show();
        d.$wrapper.find('.dv-download-template').on('click', (e) => {
            e.preventDefault();
            _download_template();
        });
    });
}

function _download_template() {
    const header = ['student_name','debit','credit','student_id','father_name','course','batch_year','admission_session','mobile','email','remarks'];
    const sample_dr = ['Ramesh Sharma','15000','','STU-001','Suresh Sharma','BTech CSE','2019','2018-19','9876543210','ramesh@example.com','sem-6 fees'];
    const sample_cr = ['Priya Verma','','2500','STU-002','Anil Verma','MBA','2020','2019-20','9123456780','priya@example.com','advance deposit'];
    const csv = header.join(',') + '\n' + sample_dr.join(',') + '\n' + sample_cr.join(',') + '\n';
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'ex_student_opening_template.csv';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
