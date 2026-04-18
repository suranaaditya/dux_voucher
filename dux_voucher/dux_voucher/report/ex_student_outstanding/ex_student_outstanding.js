frappe.query_reports['Ex Student Outstanding'] = {
    filters: [
        {
            fieldname: 'company',
            label: __('Company'),
            fieldtype: 'Link',
            options: 'Company',
            default: frappe.defaults.get_user_default('company'),
        },
        {
            fieldname: 'ex_student',
            label: __('Ex Student'),
            fieldtype: 'Link',
            options: 'Ex Student',
            get_query: () => ({
                filters: {
                    is_disabled: 0,
                    company: frappe.query_report.get_filter_value('company') || '',
                },
            }),
        },
        {
            fieldname: 'as_of_date',
            label: __('As of Date'),
            fieldtype: 'Date',
        },
        {
            fieldname: 'show_zero',
            label: __('Show Zero Balance'),
            fieldtype: 'Check',
            default: 0,
        },
    ],
};
