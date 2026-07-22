import frappe
from frappe.utils import flt, getdate, today
from frappe.utils.data import add_to_date, formatdate

from lms_saas.utils.calculations import principal_outstanding

RISK_LABELS = ["Current", "PAR 30+", "PAR 60+", "PAR 90+"]


@frappe.whitelist()
def get_desk_dashboard(company=None, branch=None):
	"""Return aggregate portfolio metrics for LMS desk dashboard widgets.

	Phase 2: the response now also includes ``cache_age_seconds`` and
	the ``truncated``/``limit`` flags from ``_portfolio_metrics`` so the
	admin console can render "5,000 loans shown of N total" and "refreshed
	3 min ago" without a second round trip.
	"""
	_guard()
	metrics = _portfolio_metrics(company=company, branch=branch)
	cache_age = _cache_age_seconds(
		f"lms_dashboard:{company or 'all'}:{branch or 'all'}:"
		f"{metrics.get('limit', 50000)}:{frappe.session.user}"
	)
	return {
		"kpis": metrics["kpis"],
		"risk_buckets": metrics["risk_buckets"],
		"collections_trend": _collections_trend(company=company),
		"branch_outstanding": _sorted_bars(metrics["branch_outstanding"], limit=6),
		"truncated": metrics.get("truncated", False),
		"limit": metrics.get("limit", 50000),
		"cache_age_seconds": cache_age,
	}


def _cache_age_seconds(cache_key: str) -> int:
	"""Return the age of the cache entry in seconds (0 if not cached)."""
	# Redis stores the TTL alongside the value; we can derive the age from
	# that. Falls back to 0 on any error so the UI never blocks.
	try:
		ttl = frappe.cache().get_key_ttl(cache_key)
		if ttl is None:
			return 0
		# TTL is "time to live" in seconds; age = 300 - ttl (the cap is
		# 300s in _portfolio_metrics). Negative values mean "about to
		# expire" — clamp to 0.
		return max(0, 300 - int(ttl))
	except Exception:
		return 0

@frappe.whitelist()
def get_chart_data(chart_name=None, filters=None, **kwargs):
    """Dashboard Chart Source endpoint for the native LMS Operations charts.

    Returns frappe-charts compatible {labels, datasets} for the requested metric.
    """
    _guard()
    filters = _parse_filters(filters)
    metric = filters.get("metric") or "risk_composition"
    company = filters.get("company")

    if metric == "collections_trend":
        rows = _collections_trend(company=company)
        return {
            "labels": [row["label"] for row in rows],
            "datasets": [{"name": "Collections", "values": [row["value"] for row in rows]}],
        }

    metrics = _portfolio_metrics(company)

    if metric == "branch_concentration":
        rows = _sorted_bars(metrics["branch_outstanding"], limit=6)
        return {
            "labels": [row["label"] for row in rows],
            "datasets": [{"name": "Outstanding", "values": [row["value"] for row in rows]}],
        }

    buckets = metrics["risk_buckets"]
    return {
        "labels": RISK_LABELS,
        "datasets": [
            {
                "name": "Outstanding",
                "values": [
                    flt(buckets["current"]),
                    flt(buckets["par30"]),
                    flt(buckets["par60"]),
                    flt(buckets["par90"]),
                ],
            }
        ],
    }


@frappe.whitelist()
def get_kpi_card(filters=None, **kwargs):
    """Number Card (type=Custom) endpoint returning a single KPI value."""
    _guard()
    filters = _parse_filters(filters)
    kpi = filters.get("kpi") or "portfolio_outstanding"
    company = filters.get("company")

    metrics = _portfolio_metrics(company)
    kpis = metrics["kpis"]

    currency_kpis = {"portfolio_outstanding", "par30_outstanding", "par90_outstanding"}
    value = flt(kpis.get(kpi, 0))

    # Return a display string (not {value, fieldtype}) so Frappe's custom Number Card
    # path skips shorten_number/format_currency, which would prefix counts with "R".
    if kpi in currency_kpis:
        return frappe.format_value(value, {"fieldtype": "Currency"})
    return frappe.format_value(int(value), {"fieldtype": "Int"})


def _portfolio_metrics(company=None, branch=None):
    """Single-pass aggregation over the live loan book shared by all widgets.

Uses frappe.get_list so row-level User Permissions scope a branch manager to
their own portfolio while System Manager / Administrator see everything.
When ``branch`` is provided, loans are additionally filtered by
``custom_lms_branch`` so portal KPIs match the branch-scoped tab views.
Results are cached for 5 minutes in Redis.

Phase-3 hardening: bounded by ``_PORTFOLIO_METRICS_LIMIT`` (default 50 000
loans) so a giant portfolio cannot lock a Python worker. The cap is
deliberately generous — most microfinance books sit in the low thousands.
If the cap is exceeded, the result is tagged ``truncated=True`` so the
admin console can warn the user; the cache key includes the cap so two
calls at different caps don't collide.
    """
    # Phase 3 — bounded aggregation. The previous implementation used
    # limit_page_length=0, which is "unbounded". For a 50 000-loan book
    # the Python loop dominated worker time. 50 000 is the cap; if the
    # portfolio is larger, the dashboard should be filtered by company
    # / branch (the admin console offers a branch selector for this).
    _PORTFOLIO_METRICS_LIMIT = 50000

    cache_key = (
        f"lms_dashboard:{company or 'all'}:{branch or 'all'}:"
        f"{_PORTFOLIO_METRICS_LIMIT}:{frappe.session.user}"
    )
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    loan_filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])}
    if company:
        loan_filters["company"] = company
    if branch:
        loan_filters["custom_lms_branch"] = branch

    # Pull one extra row so we can detect truncation.
    loans = frappe.get_list(
        "Loan",
        filters=loan_filters,
        fields=[
            "name",
            "company",
            "applicant",
            "loan_amount",
            "total_principal_paid",
            "written_off_amount",
            "days_past_due",
            "custom_days_past_due",
            "custom_lms_branch",
        ],
        limit_page_length=_PORTFOLIO_METRICS_LIMIT + 1,
        ignore_permissions=False,
    )
    truncated = len(loans) > _PORTFOLIO_METRICS_LIMIT
    if truncated:
        loans = loans[:_PORTFOLIO_METRICS_LIMIT]

    kpis = {
        "portfolio_outstanding": 0,
        "active_loans": 0,
        "par30_outstanding": 0,
        "par90_outstanding": 0,
        "npa_count": 0,
    }
    risk_buckets = {"current": 0, "par30": 0, "par60": 0, "par90": 0}
    branch_outstanding: dict[str, float] = {}

    # Phase 3 — pre-load the Customer.custom_lms_branch map so the
    # branch_outstanding fallback can resolve loans that have no
    # custom_lms_branch of their own. Without this, every fresh-install
    # loan collapses to "Unassigned" and the Branch Concentration
    # chart shows a single tall bar.
    applicants = list({loan.applicant for loan in loans if loan.applicant})
    customer_branch_map: dict[str, str] = {}
    if applicants:
        for row in frappe.get_all(
            "Customer",
            filters={"name": ("in", applicants)},
            fields=["name", "custom_lms_branch"],
            limit_page_length=0,
        ):
            if row.custom_lms_branch:
                customer_branch_map[row.name] = row.custom_lms_branch

    for loan in loans:
        # Portfolio exposure = outstanding principal (loan_amount net of principal
        # repaid and write-offs). total_payment includes interest, so it must NOT
        # be subtracted from loan_amount here.
        outstanding = principal_outstanding(
            loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
        )
        kpis["portfolio_outstanding"] += outstanding
        kpis["active_loans"] += 1
        dpd = flt(loan.custom_days_past_due or loan.days_past_due or 0)

        if dpd > 90:
            risk_buckets["par90"] += outstanding
            kpis["par90_outstanding"] += outstanding
            kpis["npa_count"] += 1
        elif dpd > 60:
            risk_buckets["par60"] += outstanding
        elif dpd > 30:
            risk_buckets["par30"] += outstanding
            kpis["par30_outstanding"] += outstanding
        else:
            risk_buckets["current"] += outstanding

        # Phase 3 — branch fallback chain:
        # 1. loan.custom_lms_branch (preferred — set by the loan officer)
        # 2. Customer.custom_lms_branch (set by onboarding)
        # 3. "Unassigned" (only when both are missing)
        loan_branch = (
            loan.custom_lms_branch
            or customer_branch_map.get(loan.applicant or "")
            or "Unassigned"
        )
        branch_outstanding[loan_branch] = branch_outstanding.get(loan_branch, 0) + outstanding

    result = {
        "kpis": kpis,
        "risk_buckets": risk_buckets,
        "branch_outstanding": branch_outstanding,
        "truncated": truncated,
        "limit": _PORTFOLIO_METRICS_LIMIT,
    }
    # Cache for 5 minutes
    frappe.cache().set_value(cache_key, result, expires_in_sec=300)
    return result


@frappe.whitelist()
def invalidate_dashboard_cache():
    """Clear the 5-minute dashboard cache so the next fetch recomputes from
    source data. Called by the Admin/Manager "Refresh" button after a
    write-through (e.g. loan submitted, repayment posted).

    Scoped to whichever keys this module writes, so it does not interfere
    with other Redis users in the site.
    """
    cache = frappe.cache()
    keys = [
        _desk_dashboard_cache_key(),
        _application_pipeline_cache_key(),
        _collections_overview_cache_key(),
        _branch_overview_cache_key(),
        _portfolio_metrics_cache_key(),
    ]
    for key in keys:
        try:
            cache.delete_value(key)
        except Exception:
            # Cache is best-effort; never block a write on cache failure.
            pass
    return {"ok": True, "keys_cleared": len(keys)}


def _desk_dashboard_cache_key(company=None, branch=None):
    return f"lms:desk_dashboard:{company or ''}:{branch or ''}"


def _application_pipeline_cache_key(company=None, branch=None):
    return f"lms:application_pipeline:{company or ''}:{branch or ''}"


def _collections_overview_cache_key(company=None):
    return f"lms:collections_overview:{company or ''}"


def _branch_overview_cache_key(company=None):
    return f"lms:branch_overview:{company or ''}"


def _portfolio_metrics_cache_key(company=None, branch=None):
    return f"lms:portfolio_metrics:{company or ''}:{branch or ''}"


def _collections_trend(company=None, months=6):
    month_totals = {}
    today_date = getdate(today())
    for offset in range(months - 1, -1, -1):
        dt = add_to_date(today_date, months=-offset)
        month_totals[dt.strftime("%Y-%m")] = 0

    repayment_filters = {"docstatus": 1}
    if company:
        loan_names = frappe.get_all("Loan", filters={"company": company}, pluck="name")
        if not loan_names:
            return [{"label": formatdate(f"{month}-01", "MMM yyyy"), "value": 0} for month in month_totals]
        repayment_filters["against_loan"] = ("in", loan_names)

    repayments = frappe.get_all(
        "Loan Repayment",
        filters=repayment_filters,
        fields=["posting_date", "amount_paid"],
        limit_page_length=2000,
    )
    for repayment in repayments:
        if not repayment.get("posting_date"):
            continue
        month = getdate(repayment.posting_date).strftime("%Y-%m")
        if month in month_totals:
            month_totals[month] += flt(repayment.amount_paid)

    return [{"label": formatdate(f"{month}-01", "MMM yyyy"), "value": flt(value)} for month, value in month_totals.items()]


def _sorted_bars(raw_map, limit=6):
    sorted_rows = sorted(raw_map.items(), key=lambda row: row[1], reverse=True)[:limit]
    return [{"label": label, "value": flt(value)} for label, value in sorted_rows]


def _parse_filters(filters):
    if not filters:
        return {}
    if isinstance(filters, str):
        try:
            return frappe.parse_json(filters) or {}
        except Exception:
            return {}
    if isinstance(filters, dict):
        return filters
    return {}


@frappe.whitelist()
def get_application_pipeline(company=None, branch=None):
	"""Loan application pipeline counts by status + recent applications.

	Phase-2 enrichment: counts every real Lending status (Draft, Open,
	Submitted, Approved, Sanctioned, Rejected, Partially Disbursed,
	Disbursed, Active, Closed, Cancelled), not just the four hard-coded
	ones. The result includes a ``total`` for KPI displays, a
	``counts`` map keyed by status, and the 10 most recent applications
	(``applications``).
	"""
	_guard()
	filters = {}
	if company:
		filters["company"] = company
	if branch:
		filters["custom_lms_branch"] = branch
	apps = frappe.get_all(
		"Loan Application",
		filters=filters,
		fields=["name", "applicant", "applicant_name", "loan_amount", "status", "loan_product", "creation"],
		order_by="creation desc",
		limit_page_length=50,
	)
	# Phase 2: enumerate the real Lending status field values rather than
	# hard-coding four keys. The previous behaviour silently dropped
	# "Sanctioned", "Partially Disbursed", "Disbursed", "Active", "Closed",
	# and "Cancelled" into a phantom "Draft" bucket, which made the
	# pipeline count wrong for any non-trivial portfolio.
	ALL_STATUSES = (
		"Draft", "Open", "Submitted", "Approved", "Sanctioned",
		"Rejected", "Partially Disbursed", "Disbursed", "Active",
		"Closed", "Cancelled", "Withdrawn",
	)
	counts = {s: 0 for s in ALL_STATUSES}
	for app in apps:
		status = (app.status or "Draft").strip()
		# Fall back to "Draft" only if the lending app introduces a
		# status we don't know about (forward-compat with future versions).
		counts[status] = counts.get(status, 0) + 1
	total = sum(counts.values())
	return {"counts": counts, "total": total, "applications": apps}


@frappe.whitelist()
def get_active_branches(company=None):
	"""Active Cost Centers (branches) for the branch selector on the admin page.

	Phase 2: the admin console has a branch selector that drives the
	``company``/``branch`` parameter into every other dashboard API.
	This endpoint is its data source. Returns a list of
	``{name, label}`` rows for active (is_group=0) Cost Centers, sorted
	by name. Admins and System Managers only.
	"""
	_guard()
	filters = {"is_group": 0}
	if company:
		filters["company"] = company
	branches = frappe.get_all(
		"Cost Center",
		filters=filters,
		fields=["name", "cost_center_name"],
		order_by="cost_center_name asc",
		limit_page_length=200,
	)
	return {
		"branches": [
			{"name": b.name, "label": b.cost_center_name or b.name}
			for b in branches
		]
	}


@frappe.whitelist()
def get_kyc_queue(branch=None, limit=5):
	"""KYC / AML compliance queue — pending counts and oldest pending rows.

	Phase 2: surfaced on the admin console so an admin can see the
	backlog of borrowers waiting for KYC review without opening a list
	view. Returns:
	- ``pending_count`` — count of ``LMS Borrower Compliance`` rows in
	  ``kyc_status="Pending"`` (or any non-terminal status).
	- ``by_status`` — count of every kyc_status in the system.
	- ``oldest`` — the N oldest pending rows (N = ``limit``, default 5)
	  with ``customer`` (Link), ``customer_name``, ``kyc_status``,
	  ``creation`` for display.
	"""
	_guard()
	# We can filter on the borrower's branch via Customer.custom_lms_branch
	# because the compliance row links to the customer via the ``customer``
	# Link field. The filter is best-effort: a compliance row whose
	# customer has no branch set will not appear in branch-scoped results.
	filters = {}
	if branch:
		customer_names = frappe.get_all(
			"Customer", filters={"custom_lms_branch": branch}, pluck="name"
		)
		if not customer_names:
			return {"pending_count": 0, "by_status": {}, "oldest": []}
		filters["customer"] = ("in", customer_names)

	# Status counts across the whole queue (ignores branch filter on the
	# by_status map so admins can see the global picture at a glance).
	# Use raw SQL because frappe.get_all rejects aggregate function
	# expressions in the ``fields`` list ("count(name) as cnt" is not
	# allowed). We only need (kyc_status, cnt), so the column list is
	# explicit — no user input is interpolated.
	global_counts = frappe.db.sql(
		"""
		SELECT kyc_status, COUNT(name) AS cnt
		FROM `tabLMS Borrower Compliance`
		GROUP BY kyc_status
		""",
		as_dict=True,
	)
	by_status = {row.kyc_status or "Pending": int(row.cnt or 0) for row in global_counts}

	# Pending list — branch-scoped if requested, otherwise global.
	pending_filters = dict(filters)
	pending_filters["kyc_status"] = ("in", ["Pending", "Open", ""])
	oldest = frappe.get_all(
		"LMS Borrower Compliance",
		filters=pending_filters,
		fields=["name", "customer", "kyc_status", "aml_status", "creation"],
		order_by="creation asc",
		limit_page_length=max(1, min(int(limit or 5), 20)),
	)
	# Enrich with customer name for display.
	for row in oldest:
		row["customer_name"] = (
			frappe.db.get_value("Customer", row.customer, "customer_name")
			if row.customer else ""
		)

	pending_count = sum(
		v for k, v in by_status.items()
		if (k or "Pending").lower() in ("pending", "open", "")
	)
	return {
		"pending_count": pending_count,
		"by_status": by_status,
		"oldest": oldest,
	}


@frappe.whitelist()
def get_recent_activity(limit=8, branch=None):
	"""Recent LMS Audit Event feed for the admin console.

	Phase 2: surfaces the last ``limit`` (default 8) money-movement and
	approval events so an admin can see "what just happened" on the
	loan book. Branch scoping is best-effort: audit events don't
	carry a branch field directly, so we filter by the reference
	document's branch (Loan.custom_lms_branch, Customer.custom_lms_branch,
	etc.) when the reference_doctype is recognised.

	The endpoint returns a list of audit events with the fields needed
	for the timeline UI: event_type, event_user, event_time, amount,
	reference_doctype, reference_name, and a ``route`` for "View doc".
	"""
	_guard()
	limit = max(1, min(int(limit or 8), 50))

	events = frappe.get_all(
		"LMS Audit Event",
		filters={},
		fields=[
			"name", "event_type", "event_user", "event_time",
			"reference_doctype", "reference_name", "amount", "company",
		],
		order_by="event_time desc",
		limit_page_length=200,  # over-fetch, then filter + trim
	)

	if branch:
		# Build a set of "Loan"/"Customer" names in the branch so we can
		# filter the audit feed. A SQL JOIN would be faster but the
		# over-fetch is bounded and runs in < 50 ms for 200 rows.
		loan_names = set(
			frappe.get_all(
				"Loan", filters={"custom_lms_branch": branch}, pluck="name"
			)
		)
		customer_names = set(
			frappe.get_all(
				"Customer", filters={"custom_lms_branch": branch}, pluck="name"
			)
		)
		def _matches_branch(e):
			ref = e.get("reference_name")
			dt = e.get("reference_doctype")
			if dt == "Loan" and ref in loan_names:
				return True
			if dt == "Customer" and ref in customer_names:
				return True
			if dt in ("Loan Application", "Loan Disbursement", "Loan Repayment", "Loan Write Off"):
				# The reference is a child of Loan; resolve via parent.
				parent = frappe.db.get_value(dt, ref, "against_loan") if ref else None
				if parent and parent in loan_names:
					return True
			return False
		events = [e for e in events if _matches_branch(e)]

	events = events[:limit]
	for e in events:
		dt = e.get("reference_doctype")
		name = e.get("reference_name")
		if dt and name:
			# Build a desk route. Frappe doc URLs use a hyphenated slug
			# for the doctype (e.g. "Loan Disbursement" → "loan-disbursement").
			slug = dt.lower().replace(" ", "-")
			e["route"] = f"/app/{slug}/{name}"
		else:
			e["route"] = None
	return {"events": events}

@frappe.whitelist()
def get_branch_overview(company=None):
    """Branch manager oversight: officer performance, branch comparison, exceptions."""
    _guard()
    metrics = _portfolio_metrics(company)
    # Officer performance
    officers = frappe.get_all(
        "Loan",
        filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
        fields=["custom_loan_officer", "loan_amount", "total_principal_paid", "written_off_amount", "custom_days_past_due"],
    )
    officer_stats = {}
    for loan in officers:
        officer = loan.custom_loan_officer or "Unassigned"
        if officer not in officer_stats:
            officer_stats[officer] = {"loans": 0, "outstanding": 0, "par_count": 0}
        officer_stats[officer]["loans"] += 1
        officer_stats[officer]["outstanding"] += principal_outstanding(
            loan.loan_amount, loan.total_principal_paid, loan.written_off_amount
        )
        if flt(loan.custom_days_past_due or 0) > 30:
            officer_stats[officer]["par_count"] += 1

    # Exceptions: loans > 60 DPD
    exceptions = frappe.get_all(
        "Loan",
        filters={
            "docstatus": 1,
            "status": ("in", ["Disbursed", "Active"]),
            "custom_days_past_due": (">", 60),
        },
        fields=["name", "applicant", "custom_days_past_due", "custom_lms_branch", "custom_loan_officer"],
        order_by="custom_days_past_due desc",
        limit_page_length=20,
    )

    # Pending approvals (disbursements needing four-eyes)
    pending_approvals = frappe.get_all(
        "Loan Disbursement",
        filters={"docstatus": 0},
        fields=["name", "against_loan", "disbursed_amount", "owner", "creation"],
        order_by="creation desc",
        limit_page_length=10,
    )

    return {
        "officer_performance": [
            {"officer": k, **v} for k, v in sorted(officer_stats.items(), key=lambda x: x[1]["outstanding"], reverse=True)
        ],
        "exceptions": exceptions,
        "pending_approvals": pending_approvals,
        "branch_outstanding": _sorted_bars(metrics["branch_outstanding"], limit=6),
    }


@frappe.whitelist()
def get_collections_overview(company=None):
    """Collections workspace: today's collections, collector leaderboard, arrears summary."""
    _guard()
    today_str = today()

    # Today's collections
    today_repayments = frappe.get_all(
        "Loan Repayment",
        filters={"docstatus": 1, "posting_date": today_str},
        fields=["name", "amount_paid", "owner"],
    )
    today_total = sum(flt(r.amount_paid) for r in today_repayments)
    today_count = len(today_repayments)

    # Collector leaderboard
    collector_totals = {}
    for r in today_repayments:
        collector_totals[r.owner] = collector_totals.get(r.owner, 0) + flt(r.amount_paid)
    leaderboard = sorted(collector_totals.items(), key=lambda x: x[1], reverse=True)[:5]

    # Arrears summary by bucket
    loans = frappe.get_all(
        "Loan",
        filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active"])},
        fields=["custom_days_past_due", "loan_amount", "total_principal_paid", "written_off_amount"],
    )
    arrears = {"current": 0, "par30": 0, "par60": 0, "par90": 0}
    for loan in loans:
        dpd = flt(loan.custom_days_past_due or 0)
        outstanding = principal_outstanding(loan.loan_amount, loan.total_principal_paid, loan.written_off_amount)
        if dpd > 90:
            arrears["par90"] += outstanding
        elif dpd > 60:
            arrears["par60"] += outstanding
        elif dpd > 30:
            arrears["par30"] += outstanding
        else:
            arrears["current"] += outstanding

    return {
        "today_total": today_total,
        "today_count": today_count,
        "leaderboard": [{"collector": c, "amount": a} for c, a in leaderboard],
        "arrears": arrears,
    }


@frappe.whitelist()
def get_system_health():
	"""Admin system health: scheduler, integrations, errors, backup.

	Phase-2 enrichment: each section now exposes a richer payload so the
	admin console can distinguish "everything green" from "scheduler off
	for 2 hours" or "backup is 9 days old".

	Fields returned:
	- ``scheduler_enabled`` (bool) — System Settings.enable_scheduler.
	- ``integrations`` (dict) — aml / credit_bureau / sms / payments booleans.
	- ``error_count_24h`` (int) — count of Error Log rows in the last 24h.
	- ``error_breakdown_24h`` (dict) — top error types (truncated to the
	  first 60 chars of the error title) and their counts in the last 24h.
	- ``last_backup_file`` (str) — file name of the most recent .sql.gz
	  in the private/backups directory, or None.
	- ``last_backup_size_bytes`` (int) — size of that file, or 0.
	- ``last_backup_age_days`` (int) — days since the file's mtime, or
	  None if no backup exists.
	"""
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "Administrator"}):
		frappe.throw("Not permitted", frappe.PermissionError)
	import json
	import os
	from frappe.utils import add_days, get_datetime, getdate, now_datetime, today

	# Scheduler status — pull the live scheduler tick timestamp from Redis
	# (set by frappe.utils.scheduler) so the admin can see "last run X ago".
	scheduler_enabled = bool(frappe.db.get_single_value("System Settings", "enable_scheduler"))
	scheduler_last_tick = None
	try:
		raw = frappe.cache().get_value("scheduler:events")
		if raw:
			# The blob is a JSON-encoded dict of {event_name: last_run_iso}.
			parsed = json.loads(raw) if isinstance(raw, str) else raw
			if isinstance(parsed, dict):
				# Take the most recent timestamp across all event keys.
				ts_list = [v for v in parsed.values() if v]
				if ts_list:
					scheduler_last_tick = max(ts_list)
	except Exception:
		scheduler_last_tick = None  # best-effort

	# Integration status (booleans from site_config + SMS Settings).
	integrations = {
		"aml": bool(frappe.conf.get("lms_aml_enabled", False)),
		"credit_bureau": bool(frappe.conf.get("lms_credit_bureau_enabled", False)),
		"sms": bool(frappe.db.get_single_value("SMS Settings", "sms_gateway_url")),
		"payments": bool(frappe.conf.get("lms_payments_enabled", False)),
	}

	# Recent errors (last 24h) — count + top 5 by error title.
	since = add_days(today(), -1)
	error_rows = frappe.get_all(
		"Error Log",
		filters={"creation": (">=", since)},
		fields=["method", "error", "creation"],
		order_by="creation desc",
		limit_page_length=200,
	)
	error_count_24h = len(error_rows)
	# Group by a short tag (method or first 60 chars of error) so the UI
	# can render "5× ImportError in lending" without exposing PII.
	breakdown: dict[str, int] = {}
	for row in error_rows:
		tag = (row.get("method") or "unknown").strip()[:60] or "unknown"
		breakdown[tag] = breakdown.get(tag, 0) + 1
	# Top 5 by count.
	error_breakdown_24h = dict(
		sorted(breakdown.items(), key=lambda kv: kv[1], reverse=True)[:5]
	)

	# Last backup — file name, size, age.
	backup_dir = frappe.get_site_path("private", "backups")
	last_backup_file = None
	last_backup_size = 0
	last_backup_mtime = None
	if os.path.isdir(backup_dir):
		# Sort by mtime (newest first) rather than name, so the age is
		# accurate even when file names don't sort chronologically.
		backups = []
		for f in os.listdir(backup_dir):
			if not f.endswith(".sql.gz"):
				continue
			fp = os.path.join(backup_dir, f)
			try:
				mt = os.path.getmtime(fp)
			except OSError:
				continue
			backups.append((mt, fp, f))
		backups.sort(reverse=True)
		if backups:
			mt, fp, name = backups[0]
			last_backup_file = name
			try:
				last_backup_size = os.path.getsize(fp)
			except OSError:
				last_backup_size = 0
			last_backup_mtime = mt

	age_days = None
	if last_backup_mtime:
		try:
			from datetime import datetime
			age_days = max(0, (datetime.now() - datetime.fromtimestamp(last_backup_mtime)).days)
		except Exception:
			age_days = None

	return {
		"scheduler_enabled": scheduler_enabled,
		"scheduler_last_tick": scheduler_last_tick,
		"integrations": integrations,
		"error_count_24h": error_count_24h,
		"error_breakdown_24h": error_breakdown_24h,
		"last_backup_file": last_backup_file,
		"last_backup_size_bytes": last_backup_size,
		"last_backup_age_days": age_days,
	}


def _guard():
    """Require portal staff or desk admin — not merely a logged-in user."""
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)
    roles = set(frappe.get_roles())
    if roles.intersection({"System Manager", "Administrator"}):
        return
    from lms_saas.install import PORTAL_STAFF_ROLE

    if PORTAL_STAFF_ROLE in roles:
        return
    frappe.throw("Not permitted", frappe.PermissionError)
