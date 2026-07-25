import frappe

from lms_saas.utils.brand import apply_portal_context
from lms_saas.utils.portal import require_persona_for_page

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/lms/account"
		raise frappe.Redirect
	# My Account is the self-service profile + KYC overview for EVERY authenticated
	# portal user (borrowers, loan officers, branch managers, collectors) — not
	# borrowers only. Staff manage their own profile here too; the desk is for
	# back-office work, not personal profile self-service.
	user = frappe.get_doc("User", frappe.session.user)
	# The "Loan portfolio" article on this page links to /lms which is the
	# borrower dashboard. Hide it for non-borrower personas (Loan Officer,
	# Branch Manager, Collector) so the page doesn't invite a staff user
	# to view a borrower-only page.
	from lms_saas.utils.portal import resolve_portal_persona
	persona = resolve_portal_persona()
	context.show_loan_portfolio = persona in (None, "Borrower")
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
