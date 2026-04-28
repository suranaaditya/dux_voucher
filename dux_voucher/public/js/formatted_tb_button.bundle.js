// dux_voucher:formatted-tb-button v1
//
// Adds a "Download Formatted TB" button to the standard ERPNext Trial
// Balance query report. The button calls the whitelisted endpoint
//   dux_voucher.formatted_reports.trial_balance.api.export_formatted_tb
// then opens the returned file_url so the browser downloads the xlsx.
//
// ── Why a property setter and not a simple onload wrap? ────────────
// `app_include_js` evaluates this script ONCE at desk boot, before
// ERPNext's trial_balance.js has loaded. That report module is loaded
// lazily on first navigation into the report and assigns:
//
//   frappe.query_reports["Trial Balance"] = { onload: function() {...} };
//
// — clobbering anything we set at boot. The framework then immediately
// calls the new onload(). A naive "save the original, wrap it" patch
// at boot, or even on `frappe.router.on('change', ...)`, races against
// that assignment.
//
// Instead, we install an Object.defineProperty setter on the
// `frappe.query_reports["Trial Balance"]` slot. When ERPNext does its
// fresh assignment, our setter wraps the incoming object's onload
// before storing it, so the framework's subsequent onload() call hits
// our wrapper. No timing sensitivity, no polling.
//
// See dux_voucher/formatted_reports/PLAN.md §4.4 for the design notes
// and the path that led here (the verify-step in PLAN.md §4.4 caught
// that Client Script's `view` field on Frappe 16.12 doesn't accept
// "Report" — `app_include_js` is the idiomatic alternative).

(function () {
    "use strict";

    // Idempotent guard + smoke-test marker. The string value is what the
    // PLAN.md §5.3 smoke test greps for in the *built* bundle — esbuild
    // strips line comments on `bench build` (`legal-comments: none`),
    // so the marker has to live in code, not in a comment, to survive.
    // Using the version string itself doubles as the loaded-flag value.
    var MARKER = "dux_voucher:formatted-tb-button v1";
    if (window._dux_formatted_tb_loaded === MARKER) return;
    window._dux_formatted_tb_loaded = MARKER;

    frappe.provide("frappe.query_reports");

    var KEY = "Trial Balance";

    // If something else has already assigned the slot before us, wrap
    // it now. Otherwise the setter handles the next assignment.
    var _stored = frappe.query_reports[KEY];

    function wrap(tb) {
        if (!tb || typeof tb !== "object" || tb._dux_wrapped) return tb;
        var orig_onload = tb.onload;
        tb.onload = function (report) {
            if (typeof orig_onload === "function") {
                orig_onload.call(this, report);
            }
            add_button(report);
        };
        tb._dux_wrapped = true;
        return tb;
    }

    function add_button(report) {
        if (!report || !report.page) return;
        // Per-page-instance guard so navigating away and back doesn't
        // accumulate duplicate buttons on a reused page wrapper.
        if (report.page._dux_formatted_tb_btn) return;
        report.page._dux_formatted_tb_btn = true;

        report.page.add_inner_button(
            __("Download Formatted TB"),
            function () { trigger_export(report); },
            __("Export"),
        );
    }

    function trigger_export(report) {
        var filters = (typeof report.get_values === "function")
                        ? report.get_values()
                        : {};
        if (!filters || !filters.company) {
            frappe.msgprint({
                message: __("Please select a Company before downloading."),
                indicator: "orange",
            });
            return;
        }
        frappe.call({
            method: "dux_voucher.formatted_reports.trial_balance.api.export_formatted_tb",
            args: { filters: filters },
            freeze: true,
            freeze_message: __("Generating formatted Trial Balance..."),
            callback: function (r) {
                if (r && r.message && r.message.file_url) {
                    window.open(r.message.file_url, "_blank");
                }
            },
        });
    }

    if (_stored) wrap(_stored);

    Object.defineProperty(frappe.query_reports, KEY, {
        configurable: true,
        enumerable: true,
        get: function () { return _stored; },
        set: function (val) { _stored = wrap(val); },
    });
})();
