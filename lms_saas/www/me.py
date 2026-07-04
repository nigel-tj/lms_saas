"""Redirect legacy /me to the branded LMS account hub for portal borrowers."""

import frappe

from lms_saas.utils.portal import is_portal_borrower

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.throw("Please log in", frappe.PermissionError)

	if is_portal_borrower():
		frappe.local.flags.redirect_location = "/lms/account"
		raise frappe.Redirect

	# Desk / dual-role users keep Frappe default My Account.
	context.current_user = frappe.get_doc("User", frappe.session.user)
	context.show_sidebar = True
