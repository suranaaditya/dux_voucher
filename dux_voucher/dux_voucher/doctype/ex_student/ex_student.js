// Copyright (c) 2026, Dux Digitech and contributors

frappe.ui.form.on('Ex Student', {
    refresh(frm) {
        if (frm.is_new()) return;
        const bal = flt(frm.doc.opening_balance);
        const bt = frm.doc.balance_type || 'Nil';
        if (bt === 'Dr' && bal > 0.005) {
            frm.dashboard.set_headline(
                __('Balance: {0} Dr (student owes)', [format_currency(bal)]),
                'blue'
            );
        } else if (bt === 'Cr' && bal < -0.005) {
            frm.dashboard.set_headline(
                __('Balance: {0} Cr (advance)', [format_currency(Math.abs(bal))]),
                'orange'
            );
        } else {
            frm.dashboard.clear_headline();
        }
    },
});
