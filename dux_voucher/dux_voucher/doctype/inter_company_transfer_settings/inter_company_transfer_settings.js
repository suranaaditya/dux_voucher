// Inter-Company Transfer Settings — Client Script

frappe.ui.form.on('Inter-Company Transfer Settings', {

	refresh(frm) {
		_ict_settings_add_upload_button(frm);
		_ict_settings_add_template_button(frm);
	},

});


// ── Upload CSV button below the mappings table ──────────────────────────

function _ict_settings_add_upload_button(frm) {
	frm.fields_dict.mappings.$wrapper.find('.ict-upload-btn-wrap').remove();

	var $btn_wrap = $('<div class="ict-upload-btn-wrap" style="margin-top:10px;display:flex;gap:8px;align-items:center;"></div>');

	var $file_input = $('<input type="file" accept=".csv" style="display:none">');

	var $upload_btn = $('<button class="btn btn-sm btn-default">' +
		'<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" ' +
		'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
		'style="margin-right:5px;vertical-align:-1px">' +
		'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>' +
		'<polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>' +
		'Upload CSV</button>');

	$btn_wrap.append($file_input).append($upload_btn);
	frm.fields_dict.mappings.$wrapper.append($btn_wrap);

	$upload_btn.on('click', function() {
		$file_input.val('').trigger('click');
	});

	$file_input.on('change', function() {
		var file = this.files[0];
		if (!file) return;
		_ict_parse_and_load_csv(frm, file);
	});
}


// ── Download template button ────────────────────────────────────────────

function _ict_settings_add_template_button(frm) {
	frm.fields_dict.mappings.$wrapper.find('.ict-template-btn-wrap').remove();

	var $upload_wrap = frm.fields_dict.mappings.$wrapper.find('.ict-upload-btn-wrap');
	if (!$upload_wrap.length) return;

	var $template_btn = $('<button class="btn btn-sm btn-default">' +
		'<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" ' +
		'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" ' +
		'style="margin-right:5px;vertical-align:-1px">' +
		'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>' +
		'<polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
		'Download Template</button>');

	var $hint = $('<span style="font-size:11px;color:#9ca3af;margin-left:4px">' +
		'CSV format: Company, Account Label (without company suffix)</span>');

	$upload_wrap.append($template_btn).append($hint);

	$template_btn.on('click', function() {
		_ict_download_template();
	});
}


// ── Parse CSV and populate child table ─────────────────────────────────

function _ict_parse_and_load_csv(frm, file) {
	var reader = new FileReader();

	reader.onload = function(e) {
		var text = e.target.result;
		var lines = text.split('\n').map(function(l) { return l.trim(); }).filter(Boolean);

		if (!lines.length) {
			frappe.msgprint({ message: __('CSV file is empty'), indicator: 'red' });
			return;
		}

		// Detect and skip header row
		var start_row = 0;
		var first = lines[0].toLowerCase();
		if (first.includes('company') || first.includes('account') || first.includes('mapping')) {
			start_row = 1;
		}

		var data_lines = lines.slice(start_row);
		if (!data_lines.length) {
			frappe.msgprint({ message: __('No data rows found after header'), indicator: 'red' });
			return;
		}

		var rows = [];
		var errors = [];

		data_lines.forEach(function(line, idx) {
			var parts = _ict_parse_csv_line(line);
			if (parts.length < 2) {
				errors.push(__('Row {0}: Expected 2 columns, got {1} — skipped', [idx + start_row + 1, parts.length]));
				return;
			}
			var company = (parts[0] || '').trim();
			var account_label = (parts[1] || '').trim();
			if (!company || !account_label) {
				errors.push(__('Row {0}: Empty company or account label — skipped', [idx + start_row + 1]));
				return;
			}
			// Use account_label as field name — matches the child doctype field
			rows.push({ company: company, account_label: account_label });
		});

		if (!rows.length) {
			frappe.msgprint({ message: __('No valid rows found in CSV'), indicator: 'red' });
			return;
		}

		_ict_validate_and_insert_rows(frm, rows, errors);
	};

	reader.readAsText(file);
}


// ── Validate rows server-side then insert into child table ──────────────

function _ict_validate_and_insert_rows(frm, rows, parse_errors) {
	frappe.call({
		method: 'dux_voucher.dux_voucher.api.ic_transfer_api.validate_mapping_rows',
		args: { rows: JSON.stringify(rows) },
		freeze: true,
		freeze_message: __('Validating rows...'),
		callback: function(r) {
			if (!r.message) return;

			var result = r.message;
			var valid_rows = result.valid || [];
			var invalid_rows = result.invalid || [];
			var all_errors = parse_errors.concat(invalid_rows.map(function(e) {
				return __('Row skipped — {0}: {1}', [e.company, e.reason]);
			}));

			if (!valid_rows.length) {
				frappe.msgprint({
					title: __('No valid rows to import'),
					message: all_errors.join('<br>'),
					indicator: 'red',
				});
				return;
			}

			frappe.confirm(
				__(
					'<b>{0} valid rows</b> found in CSV.<br><br>' +
					'Do you want to <b>replace all existing mappings</b> or <b>append</b> to the current table?<br><br>' +
					(all_errors.length ? '<span style="color:#d97706">⚠ ' + all_errors.length + ' rows were skipped — see details after import.</span>' : ''),
					[valid_rows.length]
				),
				function() { _ict_insert_rows(frm, valid_rows, true, all_errors); },
				function() { _ict_insert_rows(frm, valid_rows, false, all_errors); }
			);

			setTimeout(function() {
				$('.modal-footer .btn-primary').text(__('Replace All'));
				$('.modal-footer .btn-default').last().text(__('Append'));
			}, 100);
		}
	});
}


function _ict_insert_rows(frm, valid_rows, replace, errors) {
	if (replace) {
		frm.clear_table('mappings');
	}

	valid_rows.forEach(function(row) {
		var child = frm.add_child('mappings');
		// account_label matches the child doctype fieldname
		frappe.model.set_value(child.doctype, child.name, 'company', row.company);
		frappe.model.set_value(child.doctype, child.name, 'account_label', row.account_label);
	});

	frm.refresh_field('mappings');

	var msg = __('<b>{0} rows added</b> to Account Mappings table.<br>Click <b>Save</b> to confirm.', [valid_rows.length]);
	if (errors.length) {
		msg += '<br><br><span style="color:#d97706">⚠ ' + errors.length + ' rows were skipped:</span><br>' +
			errors.map(function(e) { return '• ' + e; }).join('<br>');
	}

	frappe.msgprint({
		title: __('Import Complete'),
		message: msg,
		indicator: valid_rows.length ? 'green' : 'orange',
	});
}


// ── Download blank CSV template ─────────────────────────────────────────

function _ict_download_template() {
	var csv_content = 'Company,Account Label (in Branch / Divisions)\n' +
		'Ankush Shikshan Sanstha Society,Ankush Shikshan Sanstha ( Society Only )\n' +
		'GH Raisoni College Of Engineering,GH Raisoni College Of Engineering\n' +
		'(replace above rows with your actual mappings)\n';

	var blob = new Blob([csv_content], { type: 'text/csv;charset=utf-8;' });
	var url = URL.createObjectURL(blob);
	var a = document.createElement('a');
	a.href = url;
	a.download = 'IC_Mapping_Template.csv';
	a.click();
	URL.revokeObjectURL(url);
}


// ── CSV line parser (handles quoted fields) ─────────────────────────────

function _ict_parse_csv_line(line) {
	var result = [];
	var current = '';
	var in_quotes = false;

	for (var i = 0; i < line.length; i++) {
		var ch = line[i];
		if (ch === '"') {
			in_quotes = !in_quotes;
		} else if (ch === ',' && !in_quotes) {
			result.push(current);
			current = '';
		} else {
			current += ch;
		}
	}
	result.push(current);
	return result;
}
