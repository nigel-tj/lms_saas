import frappe

from lms_saas.utils.brand import apply_portal_context
from lms_saas.utils.portal import require_persona_for_page

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/apply"
		raise frappe.Redirect
	# Apply is a borrower-only flow. Staff users (Branch Manager / Loan
	# Officer / Collector) would hit a 403 from the API and see a permanent
	# "Loading…" spinner. Redirect them to their persona landing instead.
	require_persona_for_page("can_borrower")
	return apply_portal_context(context, nav_active="apply", page_js="js/lms_portal.js")
