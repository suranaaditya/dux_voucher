/* ============================================================
   Student Fee Refund — form behaviour
   Dux Digitech · dux_voucher

   Clone of Student Fee Receipt's form behaviour, with three
   substantive additions:

     1. A paid-to-date headline at the top of the form, driven by
        api/student_fee.get_student_paid_summary. Tells the operator
        at a glance whether the student has anything to be refunded.
     2. Two soft-warn confirms at validate-time (yellow dialog,
        operator confirms to override):
          * Total refund > paid to date
          * Student has no fee receipts on file
     3. Paid From Account picker (in place of Received In Account).

   Picker scoping (student → company; head → student.course;
   paid_from_account → MOP type + company), inline-create, MOP cache,
   admission_year defaulter — copied verbatim from the Receipt JS so
   the operator's muscle memory transfers.
   ============================================================ */

frappe.ui.form.on("Student Fee Refund", {
    setup(frm) {
        // Fee Head picker — scoped to student.course.
        frm.set_query("head", "heads", () => {
            const course = frm.doc.course;
            if (!course) {
                return { filters: { course: "__no_student_selected__" } };
            }
            return {
                filters: {
                    course: course,
                    is_disabled: 0,
                },
            };
        });

        // Student picker — scoped to refund.company.
        frm.set_query("student", () => {
            if (!frm.doc.company) return {};
            return {
                filters: {
                    company: frm.doc.company,
                    is_disabled: 0,
                },
            };
        });

        // Paid From Account — scoped to company + (when known) the
        // mode-of-payment's account_type. Same mechanism as the
        // Receipt's received_in_account picker.
        frm.set_query("paid_from_account", () => {
            const filters = { is_group: 0, disabled: 0 };
            if (frm.doc.company) {
                filters.company = frm.doc.company;
            }
            const mop_type = frm._mop_account_type;
            if (mop_type === "Bank" || mop_type === "Cash") {
                filters.account_type = mop_type;
            } else {
                filters.account_type = ["in", ["Bank", "Cash"]];
            }
            return { filters };
        });
    },

    refresh(frm) {
        // Detect the draft → submitted transition so the income-booking
        // dialog can auto-pop once, right after the operator submits.
        if (frm._prev_docstatus === 0 && frm.doc.docstatus === 1) {
            frm._just_submitted = true;
        }
        frm._prev_docstatus = frm.doc.docstatus;

        _refresh_mop_account_type(frm);
        _default_admission_year(frm);
        _refresh_paid_summary(frm);

        if (frm.doc.docstatus === 1 && frm.doc.backend_je) {
            frm.add_custom_button(
                __("View Journal Entry"),
                () => frappe.set_route("Form", "Journal Entry", frm.doc.backend_je)
            );
        }

        _setup_income_booking(frm);
    },

    student(frm) {
        // Switching student likely changes course → wipe stale head
        // rows so amounts entered for the old student's course don't
        // silently fail validation later.
        if (frm.doc.heads && frm.doc.heads.length) {
            frm.clear_table("heads");
        }
        frm.refresh_field("heads");

        _default_admission_year(frm);
        _refresh_paid_summary(frm);
    },

    mode_of_payment(frm) {
        if (frm.doc.paid_from_account) {
            frm.set_value("paid_from_account", null);
        }
        _refresh_mop_account_type(frm);
    },

    company(frm) {
        if (frm.doc.paid_from_account) {
            frm.set_value("paid_from_account", null);
        }
        if (frm.doc.student) {
            frm.set_value("student", null);
        }
    },

    validate(frm) {
        if (frm._refund_warning_confirmed) return;

        // total_amount on the parent is read-only and computed by the
        // server-side controller in _compute_total. JS validate fires
        // BEFORE that runs, so frm.doc.total_amount is still 0 at this
        // point. Sum the heads grid live — same approach the headline
        // uses — so the warning sees the right number.
        const total = (frm.doc.heads || [])
            .reduce((s, r) => s + flt(r.amount), 0);
        const summary = frm._paid_summary || { paid: 0, receipt_count: 0 };
        const paid = flt(summary.paid);
        const receipt_count = parseInt(summary.receipt_count || 0, 10);

        let warning = null;

        if (receipt_count === 0) {
            // No receipts on file — refund without a prior receipt is
            // unusual but not impossible (e.g. money received outside
            // the system, refund being formally recorded). Confirm.
            warning = __(
                "This student has no Student Fee Receipt on file. "
                + "Refunding without a prior receipt is unusual. Continue?"
            );
        } else if (total > paid + 0.005) {
            const overpay = total - paid;
            warning = __(
                "Refund ({0}) exceeds total paid to date ({1}). This "
                + "will leave a net Dr balance of {2} on the Admission "
                + "Fee (Provisional) liability for this student. Continue?",
                [
                    format_currency(total),
                    format_currency(paid),
                    format_currency(overpay),
                ]
            );
        }

        if (warning) {
            frappe.validated = false;
            frappe.confirm(
                warning,
                () => {
                    frm._refund_warning_confirmed = true;
                    frm.save(frm.doc.docstatus === 0 ? undefined : "Submit");
                },
                () => {
                    frappe.show_alert({
                        message: __("Cancelled. Adjust the refund and try again."),
                        indicator: "orange",
                    }, 5);
                }
            );
        }
    },
});

// Recompute headline when the heads table changes (total_amount is
// the read-only Currency on the parent, computed by the controller —
// the JS headline previews using the live grid sum).
frappe.ui.form.on("Student Fee Refund Head", {
    amount(frm) { _show_paid_summary_headline(frm); },
    head(frm)   { _show_paid_summary_headline(frm); },
    heads_remove(frm) { _show_paid_summary_headline(frm); },
});


/**
 * Fetch the Mode of Payment's `type` (Bank or Cash) and cache on the
 * form for the set_query closure to read.
 */
function _refresh_mop_account_type(frm) {
    frm._mop_account_type = null;
    if (!frm.doc.mode_of_payment) return;
    frappe.db.get_value(
        "Mode of Payment",
        frm.doc.mode_of_payment,
        "type"
    ).then((r) => {
        frm._mop_account_type = (r && r.message && r.message.type) || null;
    });
}


/**
 * Default `admission_year` on a fresh new form. Mirrors the Receipt's
 * defaulter so the operator never sees an empty required field.
 */
function _default_admission_year(frm) {
    if (!frm.is_new() || frm.doc.admission_year) return;
    frm.set_value("admission_year", _compute_indian_fy(frm.doc.posting_date));
}


/**
 * Fetch the student's paid-to-date summary and cache on the form.
 * The headline below reads from frm._paid_summary live so subsequent
 * head-row edits update the message without re-querying.
 */
function _refresh_paid_summary(frm) {
    frm._paid_summary = null;
    if (!frm.doc.student) {
        frm.dashboard.clear_headline();
        return;
    }
    frappe.call({
        method: "dux_voucher.dux_voucher.api.student_fee.get_student_paid_summary",
        args: { student: frm.doc.student },
        callback: (r) => {
            frm._paid_summary = r.message || { paid: 0, receipt_count: 0 };
            _show_paid_summary_headline(frm);
        },
    });
}


/**
 * Render the dashboard headline based on the cached paid-summary and
 * the live total_amount (sum of grid rows).
 *
 *  green   — student has paid >= proposed refund (the normal case)
 *  yellow  — refund exceeds paid (will leave a Dr on the liability)
 *  orange  — student has no receipts on file
 */
function _show_paid_summary_headline(frm) {
    const summary = frm._paid_summary;
    if (!summary) { frm.dashboard.clear_headline(); return; }

    const paid = flt(summary.paid);
    const receipt_count = parseInt(summary.receipt_count || 0, 10);

    // Sum the heads grid live for the preview.
    const refund_total = (frm.doc.heads || [])
        .reduce((s, r) => s + flt(r.amount), 0);

    if (receipt_count === 0) {
        frm.dashboard.set_headline(
            __("No fee receipts on file for this student"),
            "orange"
        );
        return;
    }

    if (refund_total > paid + 0.005) {
        const overpay = refund_total - paid;
        frm.dashboard.set_headline(
            __("Paid to date: {0} — this refund ({1}) will leave a Dr balance of {2}",
               [format_currency(paid),
                format_currency(refund_total),
                format_currency(overpay)]),
            "red"
        );
        return;
    }

    const remaining = paid - refund_total;
    frm.dashboard.set_headline(
        __("Paid to date: {0}. After this refund: {1} still held.",
           [format_currency(paid), format_currency(remaining)]),
        "green"
    );
}


/**
 * Income-booking entry points on a submitted refund:
 *   * already booked  → "View Income JE" button
 *   * remaining > 0    → primary "Book as income" button, and the dialog
 *                        auto-pops once right after submit
 *   * remaining <= 0   → nothing (fully refunded, or refund left a Dr)
 */
function _setup_income_booking(frm) {
    if (frm.doc.docstatus !== 1) return;

    // Consume the one-shot submit flag synchronously up-front so it can
    // never linger into a later refresh (e.g. a submit that had nothing
    // to book, where the async callback returns early).
    const justSubmitted = frm._just_submitted;
    frm._just_submitted = false;

    if (frm.doc.income_booked) {
        frm.add_custom_button(__("View Income JE"), () =>
            frappe.set_route("Form", "Journal Entry", frm.doc.income_je));
        return;
    }

    if (!frm.doc.student || !frm.doc.company) return;
    frappe.call({
        method: "dux_voucher.dux_voucher.api.student_fee.get_student_remaining",
        args: { student: frm.doc.student, company: frm.doc.company },
        callback: (r) => {
            const remaining = flt((r.message || {}).remaining);
            if (remaining <= 0.005) return;
            const btn = frm.add_custom_button(__("Book as income"), () =>
                _open_income_dialog(frm, remaining));
            if (btn) $(btn).removeClass("btn-default").addClass("btn-primary");
            if (justSubmitted) _open_income_dialog(frm, remaining);
        },
    });
}


/**
 * The booking dialog — shows the full remaining (read-only, per the
 * agreed "book full remaining in one click") and an editable income
 * posting date (defaults to today). Posts via student_fee.book_income.
 */
function _open_income_dialog(frm, remaining) {
    const d = new frappe.ui.Dialog({
        title: __("Book retained fee as income"),
        fields: [
            {
                fieldtype: "HTML",
                fieldname: "info",
                options:
                    '<div style="font-size:13px;line-height:1.6;color:#475569">'
                    + __("{0} is still held in the Admission Fee (Provisional) account for this student after the refund.",
                         [format_currency(remaining)])
                    + "<br>"
                    + __("Booking will <b>Dr</b> the provisional liability and <b>Cr</b> your income account, clearing the balance.")
                    + "</div>",
            },
            {
                fieldtype: "Currency",
                fieldname: "amount",
                label: __("Amount to book"),
                default: remaining,
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
                args: { refund: frm.doc.name, posting_date: values.posting_date },
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
                    frm.reload_doc();
                },
            });
        },
    });
    d.show();
}


/**
 * Indian fiscal year (Apr-Mar) for a given date string in 'FY YYYY-YY'
 * format. Mirrors the Python helper
 * ``dux_voucher.dux_voucher.doctype.student_fee_receipt.student_fee_receipt.current_admission_year``.
 */
function _compute_indian_fy(date_str) {
    const dt = date_str ? new Date(date_str) : new Date();
    if (isNaN(dt.getTime())) return "";
    const year = dt.getFullYear();
    const month = dt.getMonth() + 1;
    const start = month >= 4 ? year : year - 1;
    const end_yy = String((start + 1) % 100).padStart(2, "0");
    return `FY ${start}-${end_yy}`;
}
