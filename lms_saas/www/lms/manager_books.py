from lms_saas.utils.portal import (
	get_lms_page_context,
	require_persona,
)

no_cache = 1


def get_context(context):
	# Persona guard: only Branch Manager (or admin) may open the books & import
	# workstream. Loan Officer and Collector are sent to their persona landing
	# instead of being able to see another persona's GL / bulk-import UI.
	require_persona("Branch Manager")
	return get_lms_page_context(
		context,
		nav_key="manager_books",
		page_js="js/lms_manager_books.js",
		perm="can_manager",
		login_path="/lms/manager-books",
	)
