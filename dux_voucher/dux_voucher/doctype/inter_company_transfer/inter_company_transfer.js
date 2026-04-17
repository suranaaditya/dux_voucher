// Inter-Company Transfer — Client Script
// Two-stage flow:
// Stage 1: User A fills and submits → JE created in their company
// Stage 2: User B opens pending ICT, selects their account, clicks Confirm

frappe.ui.form.on('Inter-Company Transfer', {

	refresh(frm) {
		_ict_apply_type(frm);
		_ict_set_account_filter(frm);
		_ict_set_other_company_query(frm);
		frm.set_query('company', function() {
			return {
				query: 'dux_voucher.dux_voucher.api.ic_transfer_api.get_user_companies'
			};
		});
		_ict_show_status_banner(frm);
		_ict_add_confirm_button(frm);
	},

	transfer_type(frm) {
		frm.set_value('paid_from_account', '');
		frm.set_value('paid_to_company', '');
		frm.set_value('received_in_account', '');
		frm.set_value('received_from_company', '');
		_ict_apply_type(frm);
		_ict_set_account_filter(frm);
	},

	company(frm) {
		frm.set_value('paid_from_account', '');
		frm.set_value('received_in_account', '');
		_ict_set_account_filter(frm);
		_ict_set_other_company_query(frm);
	},

	paid_to_company(frm) {
		if (frm.doc.paid_to_company && frm.doc.paid_to_company === frm.doc.company) {
			frappe.show_alert({ message: __('Cannot select your own company'), indicator: 'red' });
			frm.set_value('paid_to_company', '');
		}
	},

	received_from_company(frm) {
		if (frm.doc.received_from_company && frm.doc.received_from_company === frm.doc.company) {
			frappe.show_alert({ message: __('Cannot select your own company'), indicator: 'red' });
			frm.set_value('received_from_company', '');
		}
	},

	before_submit(frm) {
		if (frm.doc.transfer_type === 'Payment' && !frm.doc.paid_to_company) {
			frappe.throw(__('Please select Paid To Company before submitting'));
		}
		if (frm.doc.transfer_type === 'Receipt' && !frm.doc.received_from_company) {
			frappe.throw(__('Please select Received From Company before submitting'));
		}
	},

	after_submit(frm) {
		// Reload so mirror_status and from_je populate without manual refresh
		frm.reload_doc();
	},
});


// ── Type toggle — label adjustments ────────────────────────────────────

function _ict_apply_type(frm) {
	const is_payment = frm.doc.transfer_type === 'Payment';
	if (is_payment) {
		frm.set_df_property('paid_from_account', 'description',
			__('Bank or cash account from which money was paid out'));
		frm.set_df_property('paid_to_company', 'description',
			__('The company that received this payment'));
	} else {
		frm.set_df_property('received_in_account', 'description',
			__('Bank or cash account into which money was received'));
		frm.set_df_property('received_from_company', 'description',
			__('The company that sent this payment'));
	}
	frm.refresh_fields();
}


// ── Bank/Cash filter scoped to selected company ─────────────────────────

function _ict_set_account_filter(frm) {
	if (!frm.doc.company) return;
	const filter = {
		company: frm.doc.company,
		account_type: ['in', ['Bank', 'Cash']],
		is_group: 0,
	};
	frm.set_query('paid_from_account', () => ({ filters: filter }));
	frm.set_query('received_in_account', () => ({ filters: filter }));
}


// ── Other company selector — all companies, bypasses User Permission ────

function _ict_set_other_company_query(frm) {
	const own_company = frm.doc.company || '';
	const query_opts = {
		query: 'dux_voucher.dux_voucher.api.ic_transfer_api.get_all_companies',
		filters: { exclude_company: own_company },
	};
	frm.set_query('paid_to_company', () => query_opts);
	frm.set_query('received_from_company', () => query_opts);
}


// ── Status banner ───────────────────────────────────────────────────────

function _ict_show_status_banner(frm) {
	if (frm.doc.docstatus !== 1) return;

	const other_company = frm.doc.transfer_type === 'Payment'
		? frm.doc.paid_to_company
		: frm.doc.received_from_company;

	if (frm.doc.mirror_status === 'Pending Review') {
		frm.dashboard.set_headline(
			`<span style="color:#d97706;font-weight:600">` +
			`⏳ Pending confirmation from <b>${other_company || 'other company'}</b>. ` +
			`Their accountant must open this entry and confirm receipt.` +
			`</span>`
		);
	} else if (frm.doc.mirror_status === 'Completed') {
		frm.dashboard.set_headline(
			`<span style="color:#059669;font-weight:600">` +
			`✓ Fully confirmed. Journal entries posted in both companies.` +
			`</span>`
		);
	} else if (frm.doc.mirror_status === 'Cancelled') {
		frm.dashboard.set_headline(
			`<span style="color:#dc2626;font-weight:600">` +
			`✗ Cancelled. All journal entries have been reversed.` +
			`</span>`
		);
	}
}


// ── Confirm button — shown only to User B (the other company's accountant)
function _ict_add_confirm_button(frm) {
	if (frm.doc.docstatus !== 1) return;
	if (frm.doc.mirror_status !== 'Pending Review') return;

	frappe.call({
		method: 'dux_voucher.dux_voucher.api.ic_transfer_api.can_user_confirm',
		args: { docname: frm.doc.name },
		callback: function(r) {
			if (!r.message) return;
			const label = frm.doc.transfer_type === 'Payment'
				? __('Confirm Receipt')
				: __('Confirm Payment');
			frm.add_custom_button(label, function() {
				_ict_show_confirm_dialog(frm, r.message.other_company);
			}).addClass('btn-primary');
		}
	});
}


// ── Confirm dialog — User B selects their bank/cash account ─────────────

function _ict_show_confirm_dialog(frm, other_company) {
	const is_payment = frm.doc.transfer_type === 'Payment';
	const account_label = is_payment
		? __('Account money was received into')
		: __('Account money was paid from');
	const description = is_payment
		? __(
			'Select the bank or cash account in {0} into which ₹{1} was received from {2}.',
			[other_company, frappe.format(frm.doc.amount, {fieldtype: 'Currency'}), frm.doc.company]
		  )
		: __(
			'Select the bank or cash account in {0} from which ₹{1} was paid to {2}.',
			[other_company, frappe.format(frm.doc.amount, {fieldtype: 'Currency'}), frm.doc.company]
		  );

	const dialog = new frappe.ui.Dialog({
		title: is_payment ? __('Confirm Receipt of Payment') : __('Confirm Outgoing Payment'),
		fields: [
			{
				fieldtype: 'HTML',
				options: `<div style="
					background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
					padding:12px 16px;margin-bottom:12px;font-size:13px;color:#166534;
					line-height:1.6;
				">${description}</div>`,
			},
			{
				fieldname: 'to_account',
				fieldtype: 'Link',
				label: account_label,
				options: 'Account',
				reqd: 1,
				get_query() {
					return {
						filters: {
							company: other_company,
							account_type: ['in', ['Bank', 'Cash']],
							is_group: 0,
						}
					};
				}
			},
		],
		primary_action_label: is_payment ? __('Confirm Receipt') : __('Confirm Payment'),
		primary_action(values) {
			if (!values.to_account) {
				frappe.show_alert({ message: __('Please select an account'), indicator: 'red' });
				return;
			}

			dialog.hide();

			frappe.call({
				method: 'confirm_mirror',
				doc: frm.doc,
				args: { to_account: values.to_account },
				freeze: true,
				freeze_message: __('Creating journal entry...'),
				callback(r) {
					if (!r.exc) {
						frappe.show_alert({
							message: __('Transfer confirmed. Journal entry {0} created in {1}.', [r.message, other_company]),
							indicator: 'green',
						}, 6);
						frm.reload_doc();
					}
				}
			});
		}
	});

	dialog.show();
}
