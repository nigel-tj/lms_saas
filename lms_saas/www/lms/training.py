import frappe

from lms_saas.utils.addons import require_addon
from lms_saas.utils.brand import apply_portal_context

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/training"
		raise frappe.Redirect
	require_addon("training")
	return apply_portal_context(context, nav_active="training", page_js="js/lms_training_portal.js")