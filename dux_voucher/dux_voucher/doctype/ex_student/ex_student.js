// Copyright (c) 2026, Dux Digitech and contributors

frappe.ui.form.on('Ex Student', {
    refresh(frm) {
        if (frm.is_new()) return;
        _show_balance_headline(frm, null);
        frappe.call({
            method: 'dux_voucher.dux_voucher.api.ex_student_api.get_opening_details',
            args: { ex_students: [frm.doc.name] },
        }).then((r) => _show_balance_headline(frm, (r.message || {})[frm.doc.name]));

        if (!frm.doc.is_disabled && frappe.model.can_create('Ex Student Opening Adjustment')) {
            // Correct this student's opening without cancelling their batch.
            frm.add_custom_button(__('Correct Opening'), () => {
                frappe.model.with_doctype('Ex Student Opening Adjustment', () => {
                    const doc = frappe.model.get_new_doc('Ex Student Opening Adjustment');
                    doc.company = frm.doc.company;
                    const row = frappe.model.add_child(doc, 'adjustments');
                    row.ex_student = frm.doc.name;
                    row.student_name = frm.doc.student_name;
                    // the grid shows the student's name, not the EX-STU code
                    frappe.utils.add_link_title('Ex Student', frm.doc.name, frm.doc.student_name);
                    frappe.set_route('Form', doc.doctype, doc.name);
                });
            });
        }
    },
});

function _show_balance_headline(frm, opening) {
    const parts = [];
    if (opening && opening.type !== 'Nil') {
        parts.push(__('Opening: {0} {1}', [format_currency(opening.amount), opening.type]));
    } else if (opening) {
        parts.push(__('Opening: Nil'));
    }
    const bal = flt(frm.doc.opening_balance);
    const bt = frm.doc.balance_type || 'Nil';
    let color = 'blue';
    if (bt === 'Dr' && bal > 0.005) {
        parts.push(__('Balance: {0} Dr (student owes)', [format_currency(bal)]));
    } else if (bt === 'Cr' && bal < -0.005) {
        parts.push(__('Balance: {0} Cr (advance)', [format_currency(Math.abs(bal))]));
        color = 'orange';
    } else {
        parts.push(__('Balance: Nil'));
    }
    // Frappe 16 appends a new bar on every set_headline: clear first.
    frm.dashboard.clear_headline();
    frm.dashboard.set_headline(parts.join('  ·  '), color);
}
