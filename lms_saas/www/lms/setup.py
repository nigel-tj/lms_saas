"""R52: Operations Manager Setup Portal — route stub.

T1 (issue #46) ships the persona + guard + routing. The full 9-tab
portal UI is T5 (issue #50). This stub ensures the route resolves so
the ops manager doesn't hit a 404 / redirect loop after login.

T5 will replace this file + the HTML + the JS with the full tabbed
portal (Loan Products | Loan Purposes | Credit Policies | Centers |
Lending Groups | Announcements | Document Categories | Payment
Providers | Change Requests).
"""

from lms_saas.utils.portal import get_lms_page_context

no_cache = 1


def get_context(context):
	return get_lms_page_context(
		context,
		nav_key="setup",
		page_js="js/lms_setup_portal.js",
		perm="can_setup",
		login_path="/lms/setup",
	)