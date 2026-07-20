from lms_saas.utils.portal import get_lms_page_context

no_cache = 1


def get_context(context):
	return get_lms_page_context(
		context,
		addon="field_visits",
		login_path="/lms/visits",
	)
