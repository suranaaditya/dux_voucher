/* Student Fee Settings — scope the income-account picker to ledger
   (non-group) accounts so the operator can't pick a group head. */

frappe.ui.form.on("Student Fee Settings", {
    setup(frm) {
        frm.set_query("retained_fee_income_account", () => ({
            filters: { is_group: 0 },
        }));
    },
});
