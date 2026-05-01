/* Admission Fee Register — filter UI for the script report. */

frappe.query_reports["Admission Fee Register"] = {
    filters: [
        {
            fieldname:    "company",
            label:        __("Company"),
            fieldtype:    "Link",
            options:      "Company",
            default:      frappe.defaults.get_user_default("Company"),
            reqd:         1,
        },
        {
            fieldname:    "from_date",
            label:        __("From Date"),
            fieldtype:    "Date",
            default:      _fy_start(),
            reqd:         1,
        },
        {
            fieldname:    "to_date",
            label:        __("To Date"),
            fieldtype:    "Date",
            default:      frappe.datetime.get_today(),
            reqd:         1,
        },
        {
            fieldname:    "course",
            label:        __("Course"),
            fieldtype:    "Link",
            options:      "Course",
        },
        {
            fieldname:    "admission_year",
            label:        __("Admission Year"),
            fieldtype:    "Data",
            description:  __("e.g. FY 2026-27"),
        },
        {
            fieldname:    "mode_of_payment",
            label:        __("Mode of Payment"),
            fieldtype:    "Link",
            options:      "Mode of Payment",
        },
    ],
};


/**
 * Start of the current Indian fiscal year (Apr-Mar) as YYYY-MM-DD.
 * Default for the From Date filter so the report opens to "this FY
 * year-to-date" out of the box.
 */
function _fy_start() {
    const today = frappe.datetime.now_date(true);  // Date object
    const year = today.getFullYear();
    const month = today.getMonth() + 1;  // 1-12
    const start_year = month >= 4 ? year : year - 1;
    return `${start_year}-04-01`;
}
