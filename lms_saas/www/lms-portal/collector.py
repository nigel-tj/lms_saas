"""Legacy Collector portal — redirects to /lms/collect."""

import frappe

no_cache = 1


def get_context(context):
	frappe.local.flags.redirect_location = "/lms/collect"
	raise frappe.Redirect
