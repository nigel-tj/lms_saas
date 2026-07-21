import frappe

from lms_saas.utils.brand import apply_portal_context
from lms_saas.utils.portal import require_persona_for_page

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/pay"
		raise frappe.Redirect
	require_persona_for_page("can_borrower")
	return apply_portal_context(context, nav_active="pay", page_js="js/lms_portal.js")
