import frappe

from lms_saas.install import PORTAL_STAFF_ROLE
from lms_saas.utils.brand import apply_portal_context
from lms_saas.utils.portal import resolve_portal_persona

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms"
		raise frappe.Redirect

	roles = set(frappe.get_roles(frappe.session.user))
	if PORTAL_STAFF_ROLE in roles:
		persona = resolve_portal_persona()
		routes = {
			"Loan Officer": "/lms/officer",
			"Branch Manager": "/lms/manager",
			"Collector": "/lms/collect",
		}
		staff_route = routes.get(persona)
		if staff_route:
			frappe.local.flags.redirect_location = staff_route
			raise frappe.Redirect

	return apply_portal_context(context, page_js="js/lms_portal.js")
