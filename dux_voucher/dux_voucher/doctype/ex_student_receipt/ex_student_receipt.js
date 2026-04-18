// Copyright (c) 2026, Dux Digitech and contributors
// For license information, please see license.txt

frappe.ui.form.on('Ex Student Receipt', {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.backend_je) {
            frm.add_custom_button(
                __('View Journal Entry'),
                () => frappe.set_route('Form', 'Journal Entry', frm.doc.backend_je)
            );
        }
    },

    onload(frm) {
        _apply_student_filter(frm);
        _apply_received_in_filter(frm);
    },

    company(frm) {
        _apply_student_filter(frm);
        _apply_received_in_filter(frm);
        // Reset dependent fields if company changes
        if (!frm.is_new() || frm.doc.ex_student) {
            frm.set_value('ex_student', '');
            frm.set_value('current_outstanding', 0);
            frm.set_value('received_in_account', '');
        }
    },

    ex_student(frm) {
        if (!frm.doc.ex_student) {
            frm.set_value('current_outstanding', 0);
            return;
        }
        frappe.call({
            method: 'dux_voucher.dux_voucher.api.ex_student_api.get_outstanding',
            args: { ex_student: frm.doc.ex_student },
            callback: (r) => {
                frm.set_value('current_outstanding', flt(r.message || 0));
                _show_outstanding_headline(frm);
            },
        });
    },

    mode_of_payment(frm) {
        if (!frm.doc.mode_of_payment) return;
        // Try to auto-fetch the account linked to this mode of payment for the current company
        frappe.call({
            method: 'frappe.client.get_list',
            args: {
                doctype: 'Mode of Payment Account',
                filters: { parent: frm.doc.mode_of_payment, company: frm.doc.company },
                fields: ['default_account'],
                limit: 1,
            },
            callback: (r) => {
                if (r.message && r.message.length && r.message[0].default_account) {
                    frm.set_value('received_in_account', r.message[0].default_account);
                }
            },
        });
    },

    validate(frm) {
        // Warn-but-allow overpayment
        if (frm._overpayment_confirmed) return;
        const outstanding = flt(frm.doc.current_outstanding);
        const amount = flt(frm.doc.amount);
        if (amount > outstanding + 0.005) {
            const excess = amount - outstanding;
            frappe.validated = false;
            frappe.confirm(
                __('The receipt amount ({0}) is more than the current outstanding ({1}). This will create a credit balance of {2} for this student. Continue?',
                   [format_currency(amount), format_currency(outstanding), format_currency(excess)]),
                () => {
                    frm._overpayment_confirmed = true;
                    frm.save(frm.doc.docstatus === 0 ? undefined : 'Submit');
                },
                () => {
                    frappe.show_alert({
                        message: __('Cancelled. Adjust the amount and try again.'),
                        indicator: 'orange',
                    }, 5);
                }
            );
        }
    },
});

function _apply_student_filter(frm) {
    frm.set_query('ex_student', () => ({
        filters: { company: frm.doc.company || '', is_disabled: 0 },
    }));
}

function _apply_received_in_filter(frm) {
    frm.set_query('received_in_account', () => ({
        filters: {
            company: frm.doc.company || '',
            account_type: ['in', ['Bank', 'Cash']],
            is_group: 0,
        },
    }));
}

function _show_outstanding_headline(frm) {
    const bal = flt(frm.doc.current_outstanding);
    if (bal > 0.005) {
        frm.dashboard.set_headline(
            __('Student currently owes {0}', [format_currency(bal)]),
            'blue'
        );
    } else if (bal < -0.005) {
        frm.dashboard.set_headline(
            __('Student has a credit balance of {0}', [format_currency(Math.abs(bal))]),
            'orange'
        );
    } else {
        frm.dashboard.clear_headline();
    }
}
