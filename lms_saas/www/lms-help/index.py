"""Help hub — picks the best role-based help page for the current user."""

import frappe

from lms_saas.utils.help import apply_help_page_context, get_help_page, pages_for_user

no_cache = 1


def _default_slug_for(user: str) -> str:
	"""Pick the most relevant help page for the current user.

	Admins see the admin guide. Portal staff see the page for their persona.
	Borrowers see the borrower help. Falls back to the admin guide when no
	role-specific page matches.
	"""
	# 1. Admins / System Manager: admin guide first.
	roles = set(frappe.get_roles(user)) if user and user != "Guest" else set()
	if roles.intersection({"System Manager", "Administrator"}):
		return "admin"

	# 2. Borrowers: borrower help.
	if "Customer" in roles:
		return "borrower"

	# 3. Portal staff: route by persona. The persona is on the linked
	# Employee record's custom_lms_persona field.
	try:
		from lms_saas.install import PORTAL_STAFF_ROLE
		from lms_saas.utils.brand import _get_user_persona

		if PORTAL_STAFF_ROLE in roles:
			persona = _get_user_persona(user)
			persona_slug = {
				"Loan Officer": "officer",
				"Branch Manager": "manager",
				"Collector": "collector",
			}.get(persona or "")
			if persona_slug:
				return persona_slug
			# Portal staff with no persona set: still go to manager
			# (the broadest portal page).
			return "manager"
	except Exception:
		pass

	# 4. Anything else: admin guide.
	return "admin"


def get_context(context):
	slug = (frappe.form_dict.slug or "").strip().lower()
	user = frappe.session.user or "Guest"
	if not slug:
		frappe.local.flags.redirect_location = f"/lms-help/{_default_slug_for(user)}"
		raise frappe.Redirect
	if not get_help_page(slug):
		frappe.throw("Not Found", frappe.DoesNotExistError)
	return apply_help_page_context(context, slug)
