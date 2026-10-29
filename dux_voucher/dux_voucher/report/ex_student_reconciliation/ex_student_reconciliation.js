// Copyright (c) 2026, Dux Digitech and contributors

frappe.query_reports['Ex Student Reconciliation'] = {
    filters: [
        {
            fieldname: 'company',
            label: __('Company'),
            fieldtype: 'Link',
            options: 'Company',
        },
        {
            fieldname: 'only_differences',
            label: __('Only companies with a gap'),
            fieldtype: 'Check',
            default: 1,
        },
    ],
    tree: true,
    name_field: 'name',
    parent_field: 'parent',
    initial_depth: 1,
    formatter(value, row, column, data, default_formatter) {
        value = default_formatter(value, row, column, data);
        if (!data) return value;
        if (data.indent === 0) value = '<b>' + value + '</b>';
        if (column.fieldname === 'difference' && Math.abs(flt(data.difference)) >= 0.005) {
            value = '<span style="color: var(--red-600)">' + value + '</span>';
        }
        return value;
    },
};
