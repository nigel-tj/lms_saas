import frappe

from lms_saas.utils.addons import require_addon
from lms_saas.utils.brand import apply_portal_context

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/tasks"
		raise frappe.Redirect
	require_addon("task_management")
	return apply_portal_context(context, nav_active="tasks", page_js="js/lms_tasks_portal.js")