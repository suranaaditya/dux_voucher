/* ============================================================
   dux_new_project.js  —  New Project
   Dux DigiTech  —  dux_voucher app

   A deliberately small create screen. ERPNext's Project form has 59
   fields across five tabs; a capital project at an institute needs six
   of them. Everything else stays at its default.

   The institute abbreviation is prefixed onto the project name behind
   the scenes — Project.project_name is unique across the whole site
   with no company qualifier, so without it two institutes cannot both
   have a "Hostel Block A". The operator types only the plain name and
   sees a live preview of what will be saved.

   Backed by dux_voucher.dux_voucher.api.project_api.

   Wrapped in an IIFE so the local helpers don't collide with the
   identically-named globals in the other Dux pages.
   ============================================================ */

(function () {

frappe.pages["dux-new-project"].on_page_load = function (wrapper) {
	try {
		var page = frappe.ui.make_app_page({
			parent: wrapper,
			title: "New Project",
			single_column: true,
		});
		new DuxNewProject(wrapper, page);
	} catch (e) {
		$(wrapper).find(".layout-main-section").html(
			'<div style="padding:40px;color:red;font-size:13px">Error: ' + e.message + "</div>"
		);
		console.error("dux-new-project:", e);
	}
};

function _esc(s) {
	return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
		return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
	});
}

class DuxNewProject {
	constructor(wrapper, page) {
		this.wrapper = wrapper;
		this.page = page;
		this.opts = { companies: [], project_types: [], separator: " - " };
		this._busy = false;

		this._injectStyles();
		this._renderLayout();
		this._loadOptions();
	}

	get $() { return $(this.wrapper).find(".layout-main-section"); }

	_injectStyles() {
		if (document.getElementById("dnp-styles")) return;
		var s = document.createElement("style");
		s.id = "dnp-styles";
		s.textContent = `
.dnp-wrap{padding:24px 0 60px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:680px}
.dnp-card{background:#fff;border:1px solid #e5e7eb;border-radius:10px;padding:26px 28px}
.dnp-title{font-size:17px;font-weight:700;color:#111827;letter-spacing:-.01em;margin-bottom:4px}
.dnp-sub{font-size:12.5px;color:#6b7280;line-height:1.6;margin-bottom:22px}
.dnp-row{display:flex;gap:16px;margin-bottom:16px}
.dnp-fg{flex:1;display:flex;flex-direction:column;gap:6px;min-width:0}
.dnp-fg label{font-size:10px;font-weight:700;color:#6b7280;text-transform:uppercase;letter-spacing:.08em}
.dnp-fg label .dnp-req{color:#dc2626;margin-left:2px}
.dnp-fg select,.dnp-fg input,.dnp-fg textarea{height:36px;border:1px solid #e5e7eb;border-radius:7px;padding:0 11px;font-size:13px;color:#111827;background:#fff;outline:none;transition:border .15s,box-shadow .15s;font-family:inherit;box-sizing:border-box;width:100%}
.dnp-fg textarea{height:auto;min-height:70px;padding:9px 11px;line-height:1.55;resize:vertical}
.dnp-fg select:focus,.dnp-fg input:focus,.dnp-fg textarea:focus{border-color:#0d9488;box-shadow:0 0 0 3px rgba(13,148,136,.08)}
.dnp-fg input.dnp-err,.dnp-fg select.dnp-err{border-color:#dc2626;box-shadow:0 0 0 3px rgba(220,38,38,.07)}
.dnp-hint{font-size:11px;color:#9ca3af;line-height:1.5}
.dnp-preview{background:#f0fdfa;border:1px solid #99f6e4;border-radius:8px;padding:11px 14px;margin-bottom:20px;display:none}
.dnp-preview.dnp-on{display:block}
.dnp-preview-lbl{font-size:10px;font-weight:700;color:#0f766e;text-transform:uppercase;letter-spacing:.08em;margin-bottom:4px}
.dnp-preview-val{font-size:14px;font-weight:600;color:#0f766e;font-family:'SFMono-Regular',Consolas,monospace;overflow-wrap:anywhere}
.dnp-actions{display:flex;gap:10px;align-items:center;margin-top:22px;padding-top:20px;border-top:1px solid #f3f4f6}
.dnp-btn{height:38px;padding:0 18px;border-radius:7px;font-size:13px;font-weight:600;cursor:pointer;border:1px solid #e5e7eb;background:#fff;color:#374151;font-family:inherit;transition:all .15s}
.dnp-btn:hover{background:#f9fafb}
.dnp-btn-primary{background:#0d9488;border-color:#0d9488;color:#fff}
.dnp-btn-primary:hover{background:#0f766e;border-color:#0f766e}
.dnp-btn[disabled]{opacity:.55;cursor:not-allowed}
.dnp-err-box{background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:11px 14px;font-size:12.5px;color:#991b1b;line-height:1.6;margin-bottom:18px;display:none}
.dnp-err-box.dnp-on{display:block}
.dnp-done{background:#fff;border:1px solid #99f6e4;border-radius:10px;padding:26px 28px;display:none}
.dnp-done.dnp-on{display:block}
.dnp-done-h{font-size:16px;font-weight:700;color:#111827;margin-bottom:5px}
.dnp-done-name{font-size:13px;color:#6b7280;margin-bottom:18px;line-height:1.6}
.dnp-done-name b{color:#111827}
.dnp-foot{font-size:11px;color:#9ca3af;line-height:1.6;margin-top:16px}
@media (max-width:700px){.dnp-row{flex-direction:column;gap:16px}}
`;
		document.head.appendChild(s);
	}

	_renderLayout() {
		this.$.html(`
<div class="dnp-wrap">
  <div class="dnp-card" id="dnp-form">
    <div class="dnp-title">Create a project</div>
    <div class="dnp-sub">Six fields. Everything else can be filled in later on the project itself.</div>

    <div class="dnp-err-box" id="dnp-err"></div>

    <div class="dnp-row">
      <div class="dnp-fg">
        <label>Institute<span class="dnp-req">*</span></label>
        <select id="dnp-company"><option value="">Loading…</option></select>
      </div>
    </div>

    <div class="dnp-row">
      <div class="dnp-fg">
        <label>Project name<span class="dnp-req">*</span></label>
        <input type="text" id="dnp-name" placeholder="Hostel Block A" autocomplete="off">
        <div class="dnp-hint">Just the name — the institute is added automatically.</div>
      </div>
    </div>

    <div class="dnp-preview" id="dnp-preview">
      <div class="dnp-preview-lbl">Will be saved as</div>
      <div class="dnp-preview-val" id="dnp-preview-val"></div>
    </div>

    <div class="dnp-row">
      <div class="dnp-fg">
        <label>Type</label>
        <select id="dnp-type"><option value="">Not set</option></select>
      </div>
      <div class="dnp-fg">
        <label>Estimated cost</label>
        <input type="number" id="dnp-cost" placeholder="0.00" min="0" step="0.01">
      </div>
    </div>

    <div class="dnp-row">
      <div class="dnp-fg">
        <label>Expected start</label>
        <input type="date" id="dnp-start">
      </div>
      <div class="dnp-fg">
        <label>Expected finish</label>
        <input type="date" id="dnp-end">
      </div>
    </div>

    <div class="dnp-row">
      <div class="dnp-fg">
        <label>Notes</label>
        <textarea id="dnp-notes" placeholder="Scope, site, anything worth recording."></textarea>
      </div>
    </div>

    <div class="dnp-actions">
      <button class="dnp-btn dnp-btn-primary" id="dnp-save">Create project</button>
      <button class="dnp-btn" id="dnp-reset">Clear</button>
    </div>

    <div class="dnp-foot">
      Status starts at <b>Open</b> and stays where you put it — progress is tracked manually,
      not from ERPNext Tasks.
    </div>
  </div>

  <div class="dnp-done" id="dnp-done">
    <div class="dnp-done-h">Project created</div>
    <div class="dnp-done-name" id="dnp-done-name"></div>
    <div class="dnp-actions" style="margin-top:0;padding-top:0;border-top:none">
      <button class="dnp-btn dnp-btn-primary" id="dnp-open">Open project</button>
      <button class="dnp-btn" id="dnp-another">Create another</button>
    </div>
  </div>
</div>`);
		this._bind();
	}

	_bind() {
		var self = this;
		this.$.find("#dnp-company").on("change", function () { self._preview(); });
		this.$.find("#dnp-name").on("input", function () { self._preview(); });
		this.$.find("#dnp-save").on("click", function () { self._save(); });
		this.$.find("#dnp-reset").on("click", function () { self._reset(); });
		this.$.find("#dnp-another").on("click", function () { self._reset(); });
		this.$.find("#dnp-name").on("keydown", function (e) {
			if (e.key === "Enter") { e.preventDefault(); self._save(); }
		});
	}

	_loadOptions() {
		var self = this;
		frappe.call({
			method: "dux_voucher.dux_voucher.api.project_api.get_form_options",
			callback: function (r) {
				var o = (r && r.message) || {};
				self.opts = {
					companies: o.companies || [],
					project_types: o.project_types || [],
					separator: o.separator || " - ",
				};

				var $c = self.$.find("#dnp-company");
				$c.empty().append('<option value="">Choose an institute…</option>');
				self.opts.companies.forEach(function (c) {
					$c.append('<option value="' + _esc(c.name) + '" data-abbr="' +
						_esc(c.abbr) + '">' + _esc(c.name) + "</option>");
				});
				if (self.opts.companies.length === 1) {
					$c.val(self.opts.companies[0].name);
				}

				var $t = self.$.find("#dnp-type");
				$t.empty().append('<option value="">Not set</option>');
				self.opts.project_types.forEach(function (t) {
					$t.append('<option value="' + _esc(t) + '">' + _esc(t) + "</option>");
				});

				self._preview();
			},
		});
	}

	/* Live preview of the composed name, mirroring _compose_name on the
	   server — including its "don't double up the prefix" rule. */
	_preview() {
		var abbr = this.$.find("#dnp-company option:selected").data("abbr") || "";
		var plain = ($.trim(this.$.find("#dnp-name").val() || ""));
		var $box = this.$.find("#dnp-preview");

		if (!abbr || !plain) { $box.removeClass("dnp-on"); return; }

		var sep = this.opts.separator;
		var prefix = abbr + sep;
		var composed = plain.toLowerCase().indexOf(prefix.toLowerCase()) === 0
			? abbr + sep + $.trim(plain.substring(prefix.length))
			: prefix + plain;

		this.$.find("#dnp-preview-val").text(composed);
		$box.addClass("dnp-on");
	}

	_error(msg) {
		var $e = this.$.find("#dnp-err");
		if (!msg) { $e.removeClass("dnp-on").empty(); return; }
		$e.html(msg).addClass("dnp-on");
	}

	_save() {
		if (this._busy) return;
		var self = this;

		var company = this.$.find("#dnp-company").val();
		var name = $.trim(this.$.find("#dnp-name").val() || "");
		var start = this.$.find("#dnp-start").val();
		var end = this.$.find("#dnp-end").val();

		this.$.find("#dnp-company, #dnp-name, #dnp-start, #dnp-end").removeClass("dnp-err");
		this._error("");

		if (!company) {
			this.$.find("#dnp-company").addClass("dnp-err");
			return this._error("Pick the institute this project belongs to.");
		}
		if (!name) {
			this.$.find("#dnp-name").addClass("dnp-err").focus();
			return this._error("Give the project a name.");
		}
		if (start && end && end < start) {
			this.$.find("#dnp-start, #dnp-end").addClass("dnp-err");
			return this._error("Expected finish cannot be before the start date.");
		}

		this._busy = true;
		this.$.find("#dnp-save").prop("disabled", true).text("Creating…");

		frappe.call({
			method: "dux_voucher.dux_voucher.api.project_api.create_project",
			args: {
				company: company,
				project_name: name,
				project_type: this.$.find("#dnp-type").val() || null,
				expected_start_date: start || null,
				expected_end_date: end || null,
				estimated_costing: this.$.find("#dnp-cost").val() || null,
				notes: $.trim(this.$.find("#dnp-notes").val() || "") || null,
			},
			callback: function (r) {
				self._busy = false;
				self.$.find("#dnp-save").prop("disabled", false).text("Create project");
				if (!r || !r.message) return;
				self._created = r.message;
				self.$.find("#dnp-form").hide();
				self.$.find("#dnp-done-name").html(
					"<b>" + _esc(r.message.project_name) + "</b><br>" + _esc(r.message.name)
				);
				self.$.find("#dnp-done").addClass("dnp-on");
				self.$.find("#dnp-open").off("click").on("click", function () {
					frappe.set_route("Form", "Project", self._created.name);
				});
			},
			error: function () {
				// Frappe already surfaces the server message; just restore the
				// button so the operator can correct and retry.
				self._busy = false;
				self.$.find("#dnp-save").prop("disabled", false).text("Create project");
			},
		});
	}

	_reset() {
		this.$.find("#dnp-name, #dnp-cost, #dnp-start, #dnp-end, #dnp-notes").val("");
		this.$.find("#dnp-type").val("");
		this.$.find("#dnp-company, #dnp-name, #dnp-start, #dnp-end").removeClass("dnp-err");
		this._error("");
		this.$.find("#dnp-preview").removeClass("dnp-on");
		this.$.find("#dnp-done").removeClass("dnp-on");
		this.$.find("#dnp-form").show();
		this.$.find("#dnp-name").focus();
	}
}

})();
