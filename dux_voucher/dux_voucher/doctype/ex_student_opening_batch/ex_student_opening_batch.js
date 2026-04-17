// Copyright (c) 2026, Dux Digitech and contributors
// For license information, please see license.txt

frappe.ui.form.on('Ex Student Opening Batch', {
    refresh(frm) {
        if (frm.is_new() || frm.doc.docstatus === 0) {
            if (frm.doc.company) {
                frm.add_custom_button(__('Import from CSV'), () => _open_csv_import(frm));
            }
        }

        if (frm.doc.docstatus === 1 && frm.doc.backend_je) {
            frm.add_custom_button(
                __('View Journal Entry'),
                () => frappe.set_route('Form', 'Journal Entry', frm.doc.backend_je)
            );
        }
    },

    company(frm) {
        // Filter child-table Ex Student link to this batch's company
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
    if (!frm.doc.name || frm.is_dirty()) {
        frappe.msgprint({
            title: __('Save first'),
            message: __('Please save the batch (with Company selected) before importing a CSV.'),
            indicator: 'orange',
        });
        return;
    }

    const d = new frappe.ui.Dialog({
        title: __('Import Students from CSV'),
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'help',
                options: `
                    <div class="text-muted" style="margin-bottom:8px">
                        <p><b>Expected columns (header row):</b>
                        <code>student_name</code>, <code>amount</code>,
                        <code>father_name</code>, <code>course</code>,
                        <code>batch_year</code>, <code>mobile</code>,
                        <code>email</code>, <code>remarks</code>.</p>
                        <p>Only <code>student_name</code> and <code>amount</code> are required.
                        Missing students will be auto-created for this company.</p>
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
                    let msg = __('Imported {0} rows. Created {1} new students.', [appended, created]);
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
}
