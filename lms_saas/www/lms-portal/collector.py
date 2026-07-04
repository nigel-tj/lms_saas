"""Collector dashboard context provider.

Phase 4.4: hyphen-path import replaced with ``_load_lms_portal_mixins``.
"""

import frappe

from lms_saas.utils.portal import _load_lms_portal_mixins

no_cache = 1


def get_context(context):
	mixins = _load_lms_portal_mixins()
	if mixins is None:
		# Mixins file is missing — fall back to the new persona guard.
		from lms_saas.utils.brand import apply_portal_context
		from lms_saas.utils.portal import require_persona_for_page

		require_persona_for_page("can_collect")
		return apply_portal_context(context, nav_active="collect")
	mixins.verify_portal_role("LMS Collector")
	mixins.apply_staff_portal_context(context, nav_active="collector", page_title="Collection Dashboard")

	# Fetch today's collection run sheet
	from lms_saas.api.field_collection import get_collection_run_sheet

	try:
		sheet = get_collection_run_sheet()
		context.collection_rows = sheet.get("rows", [])
	except Exception:
		context.collection_rows = []

	# Summary stats
	from lms_saas.api.dashboard import get_collections_overview

	try:
		overview = get_collections_overview()
		context.today_total = overview.get("today_total", 0)
		context.today_count = overview.get("today_count", 0)
		context.arrears = overview.get("arrears", {})
		context.leaderboard = overview.get("leaderboard", [])
	except Exception:
		context.today_total = 0
		context.today_count = 0
		context.arrears = {}
		context.leaderboard = []

	# Count overdue loans
	overdue_count = sum(1 for r in context.collection_rows if (r.get("days_past_due") or 0) > 0)
	context.overdue_count = overdue_count
	context.due_count = len(context.collection_rows)

	return context
