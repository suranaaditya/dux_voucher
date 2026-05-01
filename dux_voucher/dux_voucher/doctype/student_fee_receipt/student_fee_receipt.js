/* ============================================================
   Student Fee Receipt — form behaviour
   Dux Digitech · dux_voucher

   Two reasons this file exists, both about narrowing pickers so
   the counter operator can't pick something that would fail at
   submit-time:

   1. The Fee Head dropdown on each child row is filtered to the
      student's course, so an MBA receipt can never see BCom heads.
   2. The Student dropdown is filtered to the receipt's company so
      an operator at JEWIPL can't accidentally pick a DD student.

   Plus one small UX nicety: clearing the heads child table when the
   student changes, so amounts entered for the previous student's
   course don't silently fail validation later.
   ============================================================ */

frappe.ui.form.on("Student Fee Receipt", {
    setup(frm) {
        // Fee Head picker — scoped to student.course (read off
        // frm.doc.course which is fetch_from-populated when the user
        // picks a student). Empty list when no student is set yet,
        // surfaced via an impossible-course filter.
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

        // Student picker — scoped to the receipt's company.
        frm.set_query("student", () => {
            if (!frm.doc.company) return {};
            return {
                filters: {
                    company: frm.doc.company,
                    is_disabled: 0,
                },
            };
        });
    },

    student(frm) {
        // Switching to a different student likely means a different
        // course → wipe stale head rows so the operator doesn't carry
        // forward fee amounts from the previous student. The fetch_from
        // for student_name / father_name / course on the parent fields
        // happens automatically; this clears the table only.
        if (frm.doc.heads && frm.doc.heads.length) {
            frm.clear_table("heads");
            frm.refresh_field("heads");
        }
    },
});
