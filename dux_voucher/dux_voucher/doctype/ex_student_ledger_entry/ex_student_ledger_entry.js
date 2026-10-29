// Copyright (c) 2026, Dux Digitech and contributors
// For license information, please see license.txt

// A ledger row is posted by its voucher and never edited (the controller
// refuses it, even for Administrator): no Save button, and a way to the
// voucher that can actually change it.
frappe.ui.form.on("Ex Student Ledger Entry", {
	refresh(frm) {
		frm.disable_save();
		frm.dashboard.clear_headline();
		if (!frm.doc.voucher_type || !frm.doc.voucher_no) return;
		frm.dashboard.set_headline(
			__("Posted by {0} {1}. Read-only: to change this balance, cancel that voucher or post an Ex Student Opening Adjustment.",
				[__(frm.doc.voucher_type), frm.doc.voucher_no]),
			frm.doc.is_cancelled ? "orange" : "blue");
		frm.add_custom_button(__("Open {0}", [__(frm.doc.voucher_type)]),
			() => frappe.set_route("Form", frm.doc.voucher_type, frm.doc.voucher_no));
	},
});
