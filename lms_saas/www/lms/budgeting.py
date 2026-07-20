from lms_saas.utils.portal import get_lms_page_context

no_cache = 1


def get_context(context):
	return get_lms_page_context(
		context,
		addon="budgeting",
		login_path="/lms/budgeting",
	)
