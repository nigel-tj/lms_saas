# Copyright (c) 2026, lms_saas contributors
# License: MIT. See LICENSE
"""Admin Console desk page (`/app/lms-admin`).

Renders the admin-only operations console — a system manager view that
surfaces portfolio health, application pipeline, KYC queue, collections
status and system health in one place.

The page itself is a Frappe desk Page (defined by ``lms_admin.json``).
The ``.js`` file builds the UI; this module is responsible for:

* gating the page to System Manager / Administrator
* providing a ``get_context()`` that hands the page title + brand slug to
  the JS so the desk chrome can show "Admin Console" as the active page

The dashboard data itself is fetched from the same whitelisted APIs
already used by the manager portal:

* ``lms_saas.api.dashboard.get_desk_dashboard``
* ``lms_saas.api.dashboard.get_application_pipeline``
* ``lms_saas.api.dashboard.get_collections_overview``
* ``lms_saas.api.dashboard.get_system_health``
* ``lms_saas.api.dashboard.get_active_branches``
* ``lms_saas.api.dashboard.get_kyc_queue``
* ``lms_saas.api.dashboard.get_recent_activity``
* ``lms_saas.api.dashboard.invalidate_dashboard_cache``
"""

import frappe
from frappe import _


ADMIN_ROLES = ("System Manager", "Administrator")


def _require_admin() -> None:
    """Abort the request with a friendly 403 unless the caller is an admin."""
    user = frappe.session.user
    if user == "Administrator":
        return
    roles = set(frappe.get_roles(user))
    if not roles.intersection(ADMIN_ROLES):
        frappe.throw(
            _("Only System Managers can access the Admin Console."),
            frappe.PermissionError,
        )


def get_context(context):
    """Hand the JS the brand slug + page title.

    The page module is also where the role check fires; the page renders
    a "Not Permitted" message if a non-admin user navigates here. Desk
    Page.is_permitted() also enforces this via the ``roles`` child table
    in ``lms_admin.json``, but a defensive check at request time avoids a
    flash of chrome and gives us a clean error to log.

    In Frappe 15 ``context`` is a ``frappe._dict`` with attribute
    assignment; in Frappe 16 it can also arrive as a plain ``dict``.
    Both support item assignment, so we use ``context["…"] = …`` to
    keep the call site compatible across versions.
    """
    _require_admin()
    context["brand_slug"] = "admin"
    context["page_title"] = _("Admin Console")
    context["no_cache"] = 1
    return context
