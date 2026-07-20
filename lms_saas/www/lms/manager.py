from lms_saas.utils.portal import get_lms_page_context

no_cache = 1


def get_context(context):
	return get_lms_page_context(
		context,
		nav_key="manager",
		page_js="js/lms_manager_portal.js",
		perm="can_manager",
		login_path="/lms/manager",
	)
