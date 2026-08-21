"""Legacy Branch Manager portal — redirects to /lms/manager."""

import frappe

no_cache = 1


def get_context(context):
	frappe.local.flags.redirect_location = "/lms/manager"
	raise frappe.Redirect