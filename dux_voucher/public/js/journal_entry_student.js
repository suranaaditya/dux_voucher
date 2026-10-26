// Journal Entry — Student party picker.
// A student belongs to one company; ERPNext sets no query on the party
// field, so without this every student of every institute is offered.
// The server re-checks company and account (api/student_ledger.py).
frappe.ui.form.on("Journal Entry Account", {
    account(frm, cdt, cdn) {
        const row = locals[cdt][cdn];
        if (!(row.account || "").startsWith("Admission/Registration Fee (Provisional) - ")) return;
        // After ERPNext's own account handler (async) has reset party_type.
        frappe.after_ajax(() => {
            if (locals[cdt][cdn] && !locals[cdt][cdn].party_type) {
                frappe.model.set_value(cdt, cdn, "party_type", "Student");
            }
        });
    },
});

frappe.ui.form.on("Journal Entry", {
    onload(frm) {
        frm.set_query("party", "accounts", (doc, cdt, cdn) => {
            const row = locals[cdt][cdn];
            if (row.party_type !== "Student") return {};
            return { filters: { company: doc.company || "__none__", is_disabled: 0 } };
        });
    },
});
