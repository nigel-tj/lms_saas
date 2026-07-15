import frappe

from lms_saas.utils.addons import require_addon
from lms_saas.utils.brand import apply_portal_context

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/inventory"
		raise frappe.Redirect
	require_addon("inventory")
	return apply_portal_context(context, nav_active="inventory", page_js="js/lms_inventory_portal.js")