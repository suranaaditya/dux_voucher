/* Student Fee Refund Income — filters + per-row "Book as income" action.

   The Action column renders a primary button on rows whose student still
   has a positive provisional balance and hasn't been booked. Clicking it
   opens the same booking dialog the refund form uses, then refreshes the
   report so the row flips to "Booked". */

frappe.query_reports["Student Fee Refund Income"] = {
    filters: [
        {
            fieldname: "company",
            label: __("Company"),
            fieldtype: "Link",
            options: "Company",
            default: frappe.defaults.get_user_default("Company"),
            reqd: 1,
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date",
            default: _srfi_fy_start(),
            reqd: 1,
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date",
            default: frappe.datetime.get_today(),
            reqd: 1,
        },
        {
            fieldname: "course",
            label: __("Course"),
            fieldtype: "Link",
            options: "Course",
        },
        {
            fieldname: "status",
            label: __("Income Status"),
            fieldtype: "Select",
            options: ["All", "Pending", "Booked"].join("\n"),
            default: "All",
        },
    ],

    formatter(value, row, column, data, default_formatter) {
        if (column.fieldname === "action") {
            if (data && data.bookable) {
                return (
                    '<button class="btn btn-xs btn-primary" '
                    + 'onclick="dux_book_refund_income(\'' + data.refund + "', "
                    + (flt(data.remaining) || 0) + ')">'
                    + __("Book as income")
                    + "</button>"
                );
            }
            if (data && data.income_booked) {
                return '<span style="color:#16a34a;font-weight:600">'
                    + __("Booked") + "</span>";
            }
            return '<span style="color:#9ca3af">—</span>';
        }
        return default_formatter(value, row, column, data);
    },
};


/** Open the booking dialog for a refund. ``remaining`` is the displayed
 *  figure; the server (book_income) recomputes the authoritative amount. */
window.dux_book_refund_income = function (refund, remaining) {
    const d = new frappe.ui.Dialog({
        title: __("Book retained fee as income"),
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "info",
                options:
                    '<div style="font-size:13px;line-height:1.6;color:#475569">'
                    + __("{0} is still held in the Admission Fee (Provisional) account for this student.",
                         [format_currency(remaining || 0)])
                    + "<br>"
                    + __("Booking will <b>Dr</b> the provisional liability and <b>Cr</b> your income account.")
                    + "</div>",
            },
            {
                fieldtype: "Currency",
                fieldname: "amount",
                label: __("Amount to book"),
                default: remaining || 0,
                read_only: 1,
            },
            {
                fieldtype: "Date",
                fieldname: "posting_date",
                label: __("Income posting date"),
                default: frappe.datetime.get_today(),
                reqd: 1,
            },
        ],
        primary_action_label: __("Book as income"),
        primary_action(values) {
            frappe.call({
                method: "dux_voucher.dux_voucher.api.student_fee.book_income",
                args: { refund: refund, posting_date: values.posting_date },
                freeze: true,
                freeze_message: __("Booking income…"),
                callback: (r) => {
                    if (!r.message) return;
                    d.hide();
                    frappe.show_alert({
                        message: __("Booked {0} as income (JE {1})",
                                    [format_currency(r.message.amount), r.message.je]),
                        indicator: "green",
                    }, 7);
                    frappe.query_report.refresh();
                },
            });
        },
    });
    d.show();
};


/** Start of the current Indian fiscal year (Apr-Mar) as YYYY-MM-DD. */
function _srfi_fy_start() {
    const today = frappe.datetime.now_date(true);
    const year = today.getFullYear();
    const month = today.getMonth() + 1;
    const start_year = month >= 4 ? year : year - 1;
    return `${start_year}-04-01`;
}
