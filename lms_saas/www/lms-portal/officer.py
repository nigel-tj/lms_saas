"""Loan Officer dashboard context provider.

The shared helpers (``apply_staff_portal_context`` / ``verify_portal_role``)
live in ``www/lms-portal/mixins.py``. That path is hyphen-named, which Python
cannot import, so we load it via ``lms_saas.utils.portal._load_lms_portal_mixins``.
"""

import frappe

from lms_saas.utils.portal import _load_lms_portal_mixins

no_cache = 1


def get_context(context):
	mixins = _load_lms_portal_mixins()
	if mixins is None:
		# Mixins file is missing — fall back to the new persona guard so the
		# page still works under the v3 persona model.
		from lms_saas.utils.brand import apply_portal_context
		from lms_saas.utils.portal import require_persona_for_page

		require_persona_for_page("can_officer")
		return apply_portal_context(context, nav_active="officer")
	mixins.verify_portal_role("LMS Loan Officer")
	mixins.apply_staff_portal_context(context, nav_active="officer", page_title="Loan Officer Dashboard")

	# Application pipeline
	from lms_saas.api.dashboard import get_application_pipeline

	try:
		pipeline = get_application_pipeline()
		context.pipeline_counts = pipeline.get("counts", {})
		context.recent_applications = pipeline.get("applications", [])[:20]
	except Exception:
		context.pipeline_counts = {}
		context.recent_applications = []

	# Loan products for the new-application form
	from lms_saas.api.lms_portal import get_loan_products

	try:
		products = get_loan_products()
		context.loan_products = products.get("products", [])
	except Exception:
		context.loan_products = []

	return context
