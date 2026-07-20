from lms_saas.utils.portal import get_lms_page_context

no_cache = 1


def get_context(context):
	return get_lms_page_context(
		context,
		nav_key="officer",
		page_js="js/lms_officer_portal.js",
		perm="can_officer",
		login_path="/lms/officer",
	)
