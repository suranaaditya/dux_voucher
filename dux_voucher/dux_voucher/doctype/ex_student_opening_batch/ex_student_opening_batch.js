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

    students_table_add(frm)    { _recompute_total(frm); },
    students_table_remove(frm) { _recompute_total(frm); },
});

frappe.ui.form.on('Ex Student Opening Row', {
    amount(frm)     { _recompute_total(frm); },
    ex_student(frm) { _recompute_total(frm); },
});

function _recompute_total(frm) {
    let total = 0;
    (frm.doc.students_table || []).forEach(r => { total += flt(r.amount); });
    frm.set_value('total_amount', total);
}

function _open_csv_import(frm) {
    // Company must be set so new students can be auto-created under it.
    if (!frm.doc.company) {
        frappe.msgprint({
            title: __('Set Company'),
            message: __('Please set the Company before importing.'),
            indicator: 'orange',
        });
        return;
    }

    // If the form is new or dirty, save it first (silent), then open the dialog.
    const ensure_saved = (frm.is_new() || frm.is_dirty()) ? frm.save() : Promise.resolve();

    ensure_saved.then(() => {
        const d = new frappe.ui.Dialog({
            title: __('Import Students from CSV'),
            fields: [
                {
                    fieldtype: 'HTML',
                    fieldname: 'help',
                    options: `
                        <div class="text-muted" style="margin-bottom:8px">
                            <p><b>Expected columns (first row = header):</b><br>
                            <code>student_name</code>, <code>student_id</code>, <code>amount</code>,
                            <code>father_name</code>, <code>course</code>,
                            <code>batch_year</code>, <code>admission_session</code>,
                            <code>mobile</code>, <code>email</code>, <code>remarks</code>.</p>
                            <p>Only <code>student_name</code> and <code>amount</code> are required.
                            Any student name that doesn't already exist in <b>${frappe.utils.escape_html(frm.doc.company)}</b> will be auto-created.</p>
                            <p><a href="#" class="dv-download-template"><i class="fa fa-download"></i> Download template CSV</a></p>
                        </div>
                    `,
                },
                {
                    label: __('CSV File'),
                    fieldname: 'csv_file',
                    fieldtype: 'Attach',
                    reqd: 1,
                },
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

        // Wire up 'Download template' after the dialog renders.
        d.$wrapper.find('.dv-download-template').on('click', (e) => {
            e.preventDefault();
            _download_template();
        });
    }).catch(err => {
        // If save failed (e.g. reqd field), let Frappe's default error handling show the message.
        console.error('Save before CSV import failed', err);
    });
}

function _download_template() {
    const header = ['student_name','student_id','amount','father_name','course','batch_year','admission_session','mobile','email','remarks'];
    const sample = ['Ramesh Sharma','STU-001','15000','Suresh Sharma','BTech CSE','2019','2018-19','9876543210','ramesh@example.com','sem-6 fees'];
    const csv = header.join(',') + '\n' + sample.join(',') + '\n';
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
