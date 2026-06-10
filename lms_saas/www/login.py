"""Branded /login page — extends Frappe login context with LMS brand."""

import frappe
from frappe.utils import cint
from frappe.www.login import get_context as frappe_login_context

from lms_saas.utils.brand import apply_login_context

no_cache = True


def get_context(context):
	frappe_login_context(context)
	apply_login_context(context)
	context.logged_out = cint(frappe.local.request.args.get("logged_out"))
	if context.logged_out:
		context.lms_login["headline"] = frappe._("Signed out")
		context.lms_login["subtitle"] = frappe._("You have been logged out securely.")
		context.lms_login["logged_out_message"] = frappe._(
			"You can sign in again when you are ready."
		)
	return context
