/* ============================================================
   Student Fee Receipt — form behaviour
   Dux Digitech · dux_voucher

   Three picker scopings, all about narrowing dropdowns so the
   counter operator can't pick something that would fail at submit-
   time and so the lists are short enough to scan visually:

   1. Fee Head dropdown on each child row → student.course.
   2. Student dropdown → receipt.company.
   3. Received In Account → receipt.company AND mode-of-payment type
      (Bank or Cash, derived from Mode of Payment.type), with
      is_group=0 and disabled=0.

   Plus two UX niceties:
   - switching student clears stale head rows from the previous
     student's course
   - switching MOP or company clears the previously-picked account
     so the user re-picks one matching the new constraint
   ============================================================ */

frappe.ui.form.on("Student Fee Receipt", {
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

        // Student picker — scoped to receipt.company.
        frm.set_query("student", () => {
            if (!frm.doc.company) return {};
            return {
                filters: {
                    company: frm.doc.company,
                    is_disabled: 0,
                },
            };
        });

        // Received In Account — scoped to company and (when known)
        // the mode-of-payment's account_type. The MOP type is fetched
        // asynchronously when the user picks an MOP and cached on
        // frm._mop_account_type; the closure reads the live cache so
        // each picker open uses the latest value.
        frm.set_query("received_in_account", () => {
            const filters = { is_group: 0, disabled: 0 };
            if (frm.doc.company) {
                filters.company = frm.doc.company;
            }
            const mop_type = frm._mop_account_type;
            if (mop_type === "Bank" || mop_type === "Cash") {
                filters.account_type = mop_type;
            } else {
                // No MOP yet — show both Bank and Cash types so the
                // operator can still pick before settling on the MOP.
                filters.account_type = ["in", ["Bank", "Cash"]];
            }
            return { filters };
        });
    },

    refresh(frm) {
        _refresh_mop_account_type(frm);
        _default_admission_year(frm);
    },

    student(frm) {
        // Switching student likely changes course → wipe stale head
        // rows so amounts entered for the old student's course don't
        // silently fail validation later. Also force a refresh on the
        // heads field so the set_query closure re-evaluates with the
        // newly fetched frm.doc.course value (especially important
        // after inline-create, where fetch_from races with user
        // clicking 'Add Row').
        if (frm.doc.heads && frm.doc.heads.length) {
            frm.clear_table("heads");
        }
        frm.refresh_field("heads");

        // Inline-create takes a path that doesn't go through the
        // refresh event, so re-default admission_year here too if it's
        // still blank.
        _default_admission_year(frm);
    },

    mode_of_payment(frm) {
        // Clear the picked account so the user re-picks one matching
        // the new MOP type. The fresh fetch updates the cached type
        // before the next picker open.
        if (frm.doc.received_in_account) {
            frm.set_value("received_in_account", null);
        }
        _refresh_mop_account_type(frm);
    },

    company(frm) {
        // Clear company-scoped fields so a stale value from another
        // company can't sneak past validate.
        if (frm.doc.received_in_account) {
            frm.set_value("received_in_account", null);
        }
        if (frm.doc.student) {
            frm.set_value("student", null);
        }
    },
});


/**
 * Fetch the Mode of Payment's `type` (Bank or Cash) and cache on the
 * form for the set_query closure to read. No-op if MOP isn't set.
 *
 * Caching avoids one DB lookup per picker-open at the counter and
 * keeps the set_query callback synchronous (Frappe doesn't await
 * async filter callbacks).
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
 * Default `admission_year` on a fresh new form. The controller's
 * `before_insert` does the same defaulting on save, but that's too
 * late for the UI — the operator opens the form and sees an empty
 * required field.
 *
 * Computed sync in JS (rather than via frappe.call) so there is no
 * race with form-render events such as inline-create completion: the
 * default is set immediately on every triggering event without an
 * AJAX round-trip that could lose to a user click.
 */
function _default_admission_year(frm) {
    if (!frm.is_new() || frm.doc.admission_year) return;
    frm.set_value("admission_year", _compute_indian_fy(frm.doc.posting_date));
}

/**
 * Indian fiscal year (Apr-Mar) for a given date string in 'FY YYYY-YY'
 * format. Mirrors the Python helper
 * ``dux_voucher.dux_voucher.doctype.student_fee_receipt.student_fee_receipt.current_admission_year``
 * — keep these two in sync if the format ever changes.
 */
function _compute_indian_fy(date_str) {
    const dt = date_str ? new Date(date_str) : new Date();
    if (isNaN(dt.getTime())) return "";
    const year = dt.getFullYear();
    const month = dt.getMonth() + 1;        // 1-12
    const start = month >= 4 ? year : year - 1;
    const end_yy = String((start + 1) % 100).padStart(2, "0");
    return `FY ${start}-${end_yy}`;
}
