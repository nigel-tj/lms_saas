"""Debug helper: render /lms portal page (bench execute lms_saas.setup.debug_portal.run)."""

import traceback

import frappe
from frappe.website.page_renderers.template_page import TemplatePage


def run():
	frappe.set_user("Administrator")
	try:
		result = TemplatePage("lms", 200).render()
		data = result.data if hasattr(result, "data") else result
		print("OK", len(data) if data else 0)
	except Exception:
		traceback.print_exc()
