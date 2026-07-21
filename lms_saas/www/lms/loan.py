import frappe

from lms_saas.utils.brand import apply_portal_context
from lms_saas.utils.portal import PERSONA_LANDING, resolve_portal_persona, is_portal_borrower

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/loan"
		raise frappe.Redirect
	# /lms/loan is the legacy alias for the borrower loan overview. Send
	# every non-borrower persona to the right landing page so staff don't
	# see a borrower dashboard when they click a "Loans" link.
	if not is_portal_borrower():
		persona = resolve_portal_persona() or ""
		frappe.local.flags.redirect_location = PERSONA_LANDING.get(persona, "/lms/manager")
		raise frappe.Redirect
	return apply_portal_context(context, nav_active="loans", page_js="js/lms_portal.js")
