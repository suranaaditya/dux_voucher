"""Backend for the Dux New Project screen.

ERPNext's Project form carries 59 fields across five tabs. For a
construction / capital project at an institute, almost none of it
applies — Tasks, Timesheets, progress collection, email reminders,
customer and sales-order links are all irrelevant. Only three fields
are genuinely mandatory: ``naming_series``, ``project_name`` and
``company``.

This module backs a deliberately small create screen. It is a
convenience layer, not a replacement: the standard Project form stays
available and everything created here is an ordinary Project record.

Two behaviours here are not cosmetic and must not be dropped:

1. **The institute prefix.** ``Project.project_name`` carries
   ``unique=1`` with no company qualifier, so across the group two
   institutes cannot both create "Hostel Block A" — the second insert
   simply fails. We compose ``"{abbr} - {name}"`` so the operator types
   only the plain name and never meets that wall.

2. **``percent_complete_method = "Manual"``.** On every save,
   ``Project.update_percent_complete()`` forces ``status`` to Open or
   Completed from task-completion maths unless the project is
   Cancelled / On hold or the method is Manual. Projects here do not use
   ERPNext Tasks, so without this the status a user picks is silently
   overwritten on the next save.
"""

import frappe
from frappe import _
from frappe.utils import flt, getdate


# Separator between the institute abbreviation and the plain project
# name. Plain ASCII with spaces — searchable, and it sorts the list by
# institute for free.
NAME_SEPARATOR = " - "


# =====================================================================
# Form options
# =====================================================================

@frappe.whitelist()
def get_form_options():
    """Everything the create screen needs to render its pickers.

    Companies come from :func:`reports_api.get_permitted_companies` so
    the list honours User Permissions; the same check is re-applied in
    :func:`create_project`, because a whitelisted endpoint is reachable
    directly and a picker is not a permission boundary.
    """
    from dux_voucher.dux_voucher.api.reports_api import get_permitted_companies

    companies = []
    for name in (get_permitted_companies() or []):
        abbr = frappe.db.get_value("Company", name, "abbr")
        companies.append({"name": name, "abbr": abbr or ""})

    # Project Type is deliberately not offered. ERPNext ships Internal /
    # External / Other and nothing else exists here; all existing projects
    # leave it blank. create_project still accepts the argument, so putting
    # a real list of types back is a UI-only change.
    return {
        "companies": companies,
        "separator": NAME_SEPARATOR,
    }


# =====================================================================
# Create
# =====================================================================

@frappe.whitelist()
def create_project(company, project_name, project_type=None,
                   expected_start_date=None, expected_end_date=None,
                   estimated_costing=None, notes=None):
    """Create a Project from the six fields the small screen collects.

    Returns ``{"name": <PROJ-####>, "project_name": <prefixed name>}``.
    """
    if not frappe.has_permission("Project", "create"):
        frappe.throw(_("You are not permitted to create Projects."),
                     frappe.PermissionError)

    company = (company or "").strip()
    plain = (project_name or "").strip()

    if not company:
        frappe.throw(_("Company is required."))
    if not plain:
        frappe.throw(_("Project name is required."))

    _guard_company(company)
    abbr = _company_abbr(company)
    full_name = _compose_name(abbr, plain)

    _reject_duplicate(full_name, plain)
    start, end = _validate_dates(expected_start_date, expected_end_date)

    doc = frappe.new_doc("Project")
    doc.project_name = full_name
    doc.company = company
    doc.status = "Open"
    # See the module docstring — without this the status is overwritten
    # from task maths on the next save.
    doc.percent_complete_method = "Manual"

    if project_type:
        doc.project_type = project_type
    if start:
        doc.expected_start_date = start
    if end:
        doc.expected_end_date = end
    if estimated_costing:
        doc.estimated_costing = flt(estimated_costing)
    if notes:
        doc.notes = notes

    doc.insert()

    return {"name": doc.name, "project_name": doc.project_name}


# =====================================================================
# Guards
# =====================================================================

def _guard_company(company):
    """Re-apply company scoping server-side. The picker only narrows what
    is offered; it is not a permission boundary."""
    from dux_voucher.dux_voucher.api.reports_api import get_permitted_companies

    permitted = set(get_permitted_companies() or [])
    if permitted and company not in permitted:
        frappe.throw(
            _("You do not have access to {0}.").format(company),
            frappe.PermissionError,
        )


def _company_abbr(company):
    abbr = frappe.get_cached_value("Company", company, "abbr")
    if not abbr:
        frappe.throw(
            _("Company '{0}' has no abbreviation set. Set Company &rarr; "
              "Abbreviation before creating projects for it.").format(company)
        )
    return abbr


def _compose_name(abbr, plain):
    """Prefix the institute abbreviation, without doubling it up when the
    operator has already typed it."""
    prefix = abbr + NAME_SEPARATOR
    if plain.lower().startswith(prefix.lower()):
        return abbr + NAME_SEPARATOR + plain[len(prefix):].strip()
    return prefix + plain


def _reject_duplicate(full_name, plain):
    """``project_name`` is unique across the whole site. Catch it here so
    the operator gets a sentence instead of a database error."""
    existing = frappe.db.get_value(
        "Project", {"project_name": full_name}, ["name", "company"], as_dict=True
    )
    if existing:
        frappe.throw(
            _("A project named <strong>{0}</strong> already exists at {1} "
              "({2}). Pick a different name.")
            .format(full_name, existing.company, existing.name)
        )


def _validate_dates(start, end):
    start = getdate(start) if start else None
    end = getdate(end) if end else None
    if start and end and end < start:
        frappe.throw(_("Expected end date cannot be before the start date."))
    return start, end
