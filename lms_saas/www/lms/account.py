import frappe

from lms_saas.utils.brand import apply_portal_context
from lms_saas.utils.portal import require_persona_for_page

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/account"
		raise frappe.Redirect
	# Account is the borrower profile + KYC overview. Staff should manage
	# their own profile via the desk, not the borrower portal — redirect
	# them to their persona landing so we don't 403 on the API call below.
	require_persona_for_page("can_borrower")

	user = frappe.get_doc("User", frappe.session.user)
	apply_portal_context(context, nav_active="account", page_js="js/lms_portal.js")
	context.account_user = user
	context.account_initials = _initials(user.full_name or user.name)
	context.account_email = user.email or user.name
	return context


def _initials(name: str) -> str:
	parts = [p for p in (name or "").split() if p]
	if not parts:
		return "?"
	if len(parts) == 1:
		return parts[0][:2].upper()
	return (parts[0][0] + parts[-1][0]).upper()
