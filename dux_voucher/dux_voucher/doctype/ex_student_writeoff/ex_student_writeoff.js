// Copyright (c) 2026, Dux Digitech and contributors

frappe.ui.form.on('Ex Student Writeoff', {
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
        _apply_writeoff_account_filter(frm);
    },

    company(frm) {
        _apply_student_filter(frm);
        _apply_writeoff_account_filter(frm);
        if (!frm.is_new() || frm.doc.ex_student) {
            frm.set_value('ex_student', '');
            frm.set_value('current_outstanding', 0);
            frm.set_value('writeoff_account', '');
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
                const info = r.message || { amount: 0, abs: 0, type: 'Nil' };
                frm.set_value('current_outstanding', flt(info.amount));
                frm._outstanding_type = info.type;
                _show_outstanding_headline(frm);
            },
        });
    },

    amount(frm) { _show_outstanding_headline(frm); },
});

function _apply_student_filter(frm) {
    frm.set_query('ex_student', () => ({
        filters: { company: frm.doc.company || '', is_disabled: 0 },
    }));
}

function _apply_writeoff_account_filter(frm) {
    frm.set_query('writeoff_account', () => ({
        filters: {
            company: frm.doc.company || '',
            root_type: 'Expense',
            is_group: 0,
        },
    }));
}

function _show_outstanding_headline(frm) {
    const bal = flt(frm.doc.current_outstanding);
    const amount = flt(frm.doc.amount);

    if (bal > 0.005) {
        let msg = __('Current outstanding: {0} Dr', [format_currency(bal)]);
        let indicator = 'blue';
        if (amount > 0) {
            if (amount > bal + 0.005) {
                msg += ' \u2014 ' + __('Amount exceeds outstanding. You can write off up to {0}.', [format_currency(bal)]);
                indicator = 'red';
            } else {
                const after = bal - amount;
                msg += ' \u2014 ' + __('After write-off: {0} Dr', [format_currency(after)]);
                indicator = 'orange';
            }
        }
        frm.dashboard.set_headline(msg, indicator);
    } else if (bal < -0.005) {
        frm.dashboard.set_headline(
            __('Student has a {0} Cr balance (advance). Cannot write off a credit balance.', [format_currency(Math.abs(bal))]),
            'red'
        );
    } else {
        if (frm.doc.ex_student) {
            frm.dashboard.set_headline(__('Nil outstanding. Nothing to write off.'), 'grey');
        } else {
            frm.dashboard.clear_headline();
        }
    }
}
