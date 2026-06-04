// Copyright (c) 2026, Dux Digitech and contributors
//
// Ex Student Refund — form behaviour mirrors Ex Student Receipt but
// with two semantic inversions:
//   * The "good" balance is Cr (we owe the student); refunding when
//     Dr means we're paying someone who still owes us money. Surface
//     this as a soft warning, not a hard block — operators sometimes
//     do this for special cases (settlement, court order, etc.).
//   * Overpayment warning fires when the refund amount exceeds the
//     available Cr (i.e. would push the student into Dr territory).

frappe.ui.form.on('Ex Student Refund', {
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
        _apply_paid_from_filter(frm);
    },

    company(frm) {
        _apply_student_filter(frm);
        _apply_paid_from_filter(frm);
        if (!frm.is_new() || frm.doc.ex_student) {
            frm.set_value('ex_student', '');
            frm.set_value('current_outstanding', 0);
            frm.set_value('paid_from_account', '');
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
            _apply_paid_from_filter(frm);
            return;
        }
        // Fetch MOP type (Bank/Cash/General) — drives the account filter
        frappe.db.get_value('Mode of Payment', frm.doc.mode_of_payment, 'type', (r) => {
            frm._mop_type = (r && r.type) || null;
            _apply_paid_from_filter(frm);

            // If current account doesn't match the MOP type, clear it
            if (frm.doc.paid_from_account) {
                frappe.db.get_value('Account', frm.doc.paid_from_account, 'account_type', (ar) => {
                    const at = ar && ar.account_type;
                    if (frm._mop_type && at && at !== frm._mop_type) {
                        frm.set_value('paid_from_account', '');
                    }
                });
            }
        });

        // Auto-fill the default account for this MOP + company
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
                    frm.set_value('paid_from_account', r.message[0].default_account);
                }
            },
        });
    },

    amount(frm) { _show_outstanding_headline(frm); },

    validate(frm) {
        if (frm._refund_warning_confirmed) return;

        // current_outstanding is signed: positive = Dr (student owes),
        // negative = Cr (we owe student). Available credit for refund
        // is therefore -current_outstanding (only meaningful when Cr).
        const outstanding = flt(frm.doc.current_outstanding);
        const amount = flt(frm.doc.amount);
        const available_cr = -outstanding;          // positive when Cr
        const overpay = amount - Math.max(available_cr, 0);

        let warning = null;
        if (outstanding > 0.005) {
            // Student is Dr — refunding makes accounting sense only in
            // edge cases. Warn and require confirmation.
            warning = __(
                'This student currently OWES the institution {0} (Dr balance). '
                + 'Refunding will increase that debt further. Continue?',
                [format_currency(outstanding)]
            );
        } else if (overpay > 0.005) {
            // Some Cr available but amount exceeds it — partial overpay.
            warning = __(
                'The refund amount ({0}) exceeds the available credit ({1}). '
                + 'This will leave the student with a Dr balance of {2}. Continue?',
                [
                    format_currency(amount),
                    format_currency(Math.max(available_cr, 0)),
                    format_currency(overpay),
                ]
            );
        }

        if (warning) {
            frappe.validated = false;
            frappe.confirm(
                warning,
                () => {
                    frm._refund_warning_confirmed = true;
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

function _apply_paid_from_filter(frm) {
    frm.set_query('paid_from_account', () => {
        const filters = {
            company: frm.doc.company || '',
            is_group: 0,
        };
        if (frm._mop_type === 'Cash') {
            filters.account_type = 'Cash';
        } else if (frm._mop_type === 'Bank') {
            filters.account_type = 'Bank';
        } else {
            // No MOP type — allow both Bank and Cash
            filters.account_type = ['in', ['Bank', 'Cash']];
        }
        return { filters };
    });
}

function _show_outstanding_headline(frm) {
    const bal = flt(frm.doc.current_outstanding);
    const amount = flt(frm.doc.amount);
    let msg, indicator;

    if (bal < -0.005) {
        // Cr balance — this is the normal "refund-eligible" case.
        msg = __('Available credit: {0} Cr', [format_currency(Math.abs(bal))]);
        indicator = 'green';
    } else if (bal > 0.005) {
        msg = __('Student still owes {0} Dr — a refund will push the balance further Dr',
                 [format_currency(bal)]);
        indicator = 'red';
    } else {
        // Nil — refunding without a credit balance is unusual; surface it.
        if (amount > 0.005) {
            frm.dashboard.set_headline(
                __('No outstanding balance — a refund will create a Dr balance of {0}',
                   [format_currency(amount)]),
                'orange'
            );
            return;
        }
        frm.dashboard.clear_headline();
        return;
    }

    // Overpayment overlay — refund > available Cr means the student
    // ends up Dr after this voucher.
    if (amount > 0.005) {
        const available_cr = Math.max(-bal, 0);
        const overpay = amount - available_cr;
        if (overpay > 0.005) {
            msg += ' — ' + __('This refund will leave a Dr balance of {0}',
                              [format_currency(overpay)]);
            indicator = 'red';
        }
    }

    frm.dashboard.set_headline(msg, indicator);
}
