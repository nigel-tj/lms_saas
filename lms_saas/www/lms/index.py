import frappe

from lms_saas.utils.brand import apply_portal_context
from lms_saas.utils.portal import PERSONA_LANDING, is_portal_borrower, resolve_portal_persona

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms"
		raise frappe.Redirect

	# Persona landing: /lms is the borrower home. Staff who land here (brand
	# logo, bookmarks, Role.home_page misfires) must be sent to their own
	# dashboard — otherwise a Branch Manager sees "Total outstanding ZAR 0".
	if not is_portal_borrower() and frappe.session.user != "Administrator":
		persona = resolve_portal_persona()
		if persona and persona in PERSONA_LANDING and PERSONA_LANDING[persona] != "/lms":
			frappe.local.flags.redirect_location = PERSONA_LANDING[persona]
			raise frappe.Redirect
		# Portal staff without a persona still shouldn't see the borrower book.
		from lms_saas.install import PORTAL_STAFF_ROLE

		if PORTAL_STAFF_ROLE in set(frappe.get_roles()):
			frappe.local.flags.redirect_location = "/lms/manager"
			raise frappe.Redirect

	return apply_portal_context(context, page_js="js/lms_portal.js")
