// Copyright (c) 2026, Dux Digitech and contributors

frappe.ui.form.on('Ex Student Receipt', {
    refresh(frm) {
        if (frm.doc.docstatus === 1 && frm.doc.backend_je) {
            frm.add_custom_button(
                __('View Journal Entry'),
                () => frappe.set_route('Form', 'Journal Entry', frm.doc.backend_je)
            );
        }
        _show_outstanding_headline(frm);
    },

    onload(frm) {
        _apply_student_filter(frm);
        _apply_received_in_filter(frm);
    },

    company(frm) {
        _apply_student_filter(frm);
        _apply_received_in_filter(frm);
        if (!frm.is_new() || frm.doc.ex_student) {
            frm.set_value('ex_student', '');
            frm.set_value('current_outstanding', 0);
            frm.set_value('received_in_account', '');
        }
    },

    ex_student(frm) {
        if (!frm.doc.ex_student) {
            frm.set_value('current_outstanding', 0);
            frm.dashboard.clear_headline();
            return;
        }
        frappe.call({
            method: 'dux_voucher.dux_voucher.api.ex_student_api.get_outstanding',
            args: { ex_student: frm.doc.ex_student },
            callback: (r) => {
                const info = r.message || {amount: 0, abs: 0, type: 'Nil'};
                frm.set_value('current_outstanding', flt(info.amount));
                frm._outstanding_type = info.type;
                _show_outstanding_headline(frm);
            },
        });
    },

    mode_of_payment(frm) {
        if (!frm.doc.mode_of_payment) {
            frm._mop_type = null;
            _apply_received_in_filter(frm);
            return;
        }
        // Fetch MOP type (Bank/Cash/General) -- drives the account filter
        frappe.db.get_value('Mode of Payment', frm.doc.mode_of_payment, 'type', (r) => {
            frm._mop_type = (r && r.type) || null;
            _apply_received_in_filter(frm);

            // If current account doesn't match the MOP type, clear it
            if (frm.doc.received_in_account) {
                frappe.db.get_value('Account', frm.doc.received_in_account, 'account_type', (ar) => {
                    const at = ar && ar.account_type;
                    if (frm._mop_type && at && at !== frm._mop_type) {
                        frm.set_value('received_in_account', '');
                    }
                });
            }
        });

        // Auto-fill the default account for this MOP + company (if set in Mode of Payment Account)
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

    amount(frm) { _show_outstanding_headline(frm); },

    validate(frm) {
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
    frm.set_query('received_in_account', () => {
        const filters = {
            company: frm.doc.company || '',
            is_group: 0,
        };
        if (frm._mop_type === 'Cash') {
            filters.account_type = 'Cash';
        } else if (frm._mop_type === 'Bank') {
            filters.account_type = 'Bank';
        } else {
            // No MOP type (not set or General) -- allow both Bank and Cash
            filters.account_type = ['in', ['Bank', 'Cash']];
        }
        return { filters };
    });
}

function _show_outstanding_headline(frm) {
    const bal = flt(frm.doc.current_outstanding);
    const amount = flt(frm.doc.amount);
    let msg, indicator;
    if (bal > 0.005) {
        msg = __('Outstanding: {0} Dr (student owes)', [format_currency(bal)]);
        indicator = 'blue';
    } else if (bal < -0.005) {
        msg = __('Outstanding: {0} Cr (advance balance)', [format_currency(Math.abs(bal))]);
        indicator = 'orange';
    } else {
        frm.dashboard.clear_headline();
        return;
    }
    if (amount > 0 && amount > bal + 0.005) {
        const excess = amount - bal;
        msg += ' — ' + __('This receipt will create a Cr balance of {0}', [format_currency(excess)]);
        indicator = 'red';
    }
    frm.dashboard.set_headline(msg, indicator);
}
