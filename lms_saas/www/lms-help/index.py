import frappe

from lms_saas.utils.help import apply_help_page_context, get_help_page

no_cache = 1


def get_context(context):
	slug = (frappe.form_dict.slug or "").strip().lower()
	if not slug:
		frappe.local.flags.redirect_location = "/lms-help/staff"
		raise frappe.Redirect
	if not get_help_page(slug):
		frappe.throw("Not Found", frappe.DoesNotExistError)
	return apply_help_page_context(context, slug)
