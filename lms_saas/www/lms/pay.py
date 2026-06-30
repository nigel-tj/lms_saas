import frappe

from lms_saas.utils.brand import apply_portal_context

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/pay"
		raise frappe.Redirect
	return apply_portal_context(context, nav_active="pay")
