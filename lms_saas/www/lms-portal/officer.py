"""Legacy Loan Officer portal — redirects to /lms/officer."""

import frappe

no_cache = 1


def get_context(context):
	frappe.local.flags.redirect_location = "/lms/officer"
	raise frappe.Redirect
