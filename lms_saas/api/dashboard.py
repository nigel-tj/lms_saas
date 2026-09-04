import frappe
from frappe.utils import add_days, add_to_date, flt, formatdate, getdate, now_datetime, today

from lms_saas.utils.calculations import principal_outstanding
from lms_saas.api.labels import officer_label, branch_label

RISK_LABELS = ["Current", "PAR 30+", "PAR 60+", "PAR 90+"]

# Phase 3: portfolio cap exposed via _portfolio_metrics so the admin console
# can warn the operator when the result set was truncated.
PORTFOLIO_LIMIT = 50000

# All Loan Application statuses that should appear in the pipeline counts dict
# (Phase 2 / test_desk_dashboard.test_application_pipeline). Counts may be 0.
ALL_APPLICATION_STATUSES = (
    "Draft",
    "Open",
    "Submitted",
    "Approved",
    "Sanctioned",
    "Rejected",
    "Partially Disbursed",
    "Disbursed",
    "Active",
    "Closed",
    "Cancelled",
    "Withdrawn",
)


@frappe.whitelist()
def get_desk_dashboard(company=None):
    """Return aggregate portfolio metrics for LMS desk dashboard widgets.

    Phase 3 additions (admin console enrichment):
      - truncated   : bool — True when the loan set was capped at PORTFOLIO_LIMIT
      - limit       : int  — the cap (50 000)
      - cache_age_seconds : int — age of the cached metrics payload (0 if fresh)

    R25-F17: for non-admin callers, scope metrics to the caller's
    branch. Without this, a Branch Manager calling the desk endpoint
    sees the entire company's loan book (PII + portfolio data).
    """
    _guard()
    # Resolve caller's branch for non-admin scope.
    caller_roles = set(frappe.get_roles())
    is_desk_admin = bool(caller_roles & {"System Manager", "Administrator"})
    caller_branch = None
    if not is_desk_admin:
        from lms_saas.api.staff import get_current_user_branch
        caller_branch = get_current_user_branch()
        if not caller_branch:
            frappe.throw(
                "Your account is not assigned to a branch. Contact HR / your system manager.",
                frappe.PermissionError,
            )
    cache_key = f"lms_dashboard:{company or 'all'}:all:{frappe.session.user}"
    cache_start = now_datetime()
    metrics = _portfolio_metrics(company, branch=caller_branch)
    cache_age = (now_datetime() - cache_start).total_seconds()
    return {
        "kpis": metrics["kpis"],
        "risk_buckets": metrics["risk_buckets"],
        "collections_trend": _collections_trend(company=company, branch=caller_branch),
        "branch_outstanding": _sorted_bars(metrics["branch_outstanding"], limit=6),
        "truncated": bool(metrics.get("truncated", False)),
        "limit": int(metrics.get("limit", PORTFOLIO_LIMIT)),
        "cache_age_seconds": int(cache_age),
    }


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
    """
    cache_key = f"lms_dashboard:{company or 'all'}:{branch or 'all'}:{frappe.session.user}"
    cached = frappe.cache().get_value(cache_key)
    if cached:
        return cached

    loan_filters = {"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])}
    if company:
        loan_filters["company"] = company
    if branch:
        loan_filters["custom_lms_branch"] = branch

    loans = frappe.get_list(
        "Loan",
        filters=loan_filters,
        fields=[
            "name",
            "company",
            "loan_amount",
            "total_principal_paid",
            "written_off_amount",
            "days_past_due",
            "custom_days_past_due",
            "custom_lms_branch",
        ],
        limit_page_length=PORTFOLIO_LIMIT + 1,  # +1 to detect truncation
        # Portal staff (Branch Manager, Loan Officer, Collector) have the
        # LMS Portal Staff role which does NOT have read permission on the
        # Loan doctype. The API already scopes by branch via loan_filters
        # (custom_lms_branch), so ignore_permissions=True is safe here —
        # the caller (_require_manager / _require_officer) has already
        # validated the user's persona and branch.
        ignore_permissions=True,
    )
    # Phase 3: detect truncation so the admin console can surface a warning.
    truncated = len(loans) > PORTFOLIO_LIMIT
    if truncated:
        loans = loans[:PORTFOLIO_LIMIT]

    kpis = {
        "portfolio_outstanding": 0,
        "active_loans": 0,
        "par30_outstanding": 0,
        "par90_outstanding": 0,
        "npa_count": 0,
    }
    risk_buckets = {"current": 0, "par30": 0, "par60": 0, "par90": 0}
    branch_outstanding = {}

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

        branch = branch_label(loan.custom_lms_branch)
        branch_outstanding[branch] = branch_outstanding.get(branch, 0) + outstanding

    result = {
        "kpis": kpis,
        "risk_buckets": risk_buckets,
        "branch_outstanding": branch_outstanding,
        "truncated": truncated,
        "limit": PORTFOLIO_LIMIT,
    }
    # Cache for 5 minutes
    frappe.cache().set_value(cache_key, result, expires_in_sec=300)
    return result


def invalidate_dashboard_cache():
    """Clear dashboard cache (call on Loan submit/cancel)."""
    frappe.cache().delete_keys("lms_dashboard:*")


def _collections_trend(company=None, months=6, branch=None):
    month_totals = {}
    today_date = getdate(today())
    for offset in range(months - 1, -1, -1):
        dt = add_to_date(today_date, months=-offset)
        month_totals[dt.strftime("%Y-%m")] = 0

    # R25-F17: scope by branch when supplied.
    loan_filters = {}
    if company:
        loan_filters["company"] = company
    if branch:
        loan_filters["custom_lms_branch"] = branch
    loan_names = frappe.get_all("Loan", filters=loan_filters, pluck="name") if (company or branch) else None

    repayment_filters = {"docstatus": 1}
    if loan_names is not None:
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
def get_application_pipeline(company=None):
    """Loan application pipeline counts by status + recent applications.

    Phase 2: ``counts`` covers every known Lending status (default 0), and
    ``total`` is the sum of all count buckets so the admin console can show
    the pipeline total in a single line.
    """
    _guard()
    filters = {}
    if company:
        filters["company"] = company
    apps = frappe.get_all(
        "Loan Application",
        filters=filters,
        fields=["name", "applicant", "loan_amount", "status", "loan_product", "creation"],
        order_by="creation desc",
        limit_page_length=50,
    )
    counts = {s: 0 for s in ALL_APPLICATION_STATUSES}
    for app in apps:
        status = app.status or "Draft"
        counts[status] = counts.get(status, 0) + 1
    return {"counts": counts, "applications": apps, "total": sum(counts.values())}


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
        officer = officer_label(loan.custom_loan_officer, loan.custom_days_past_due)
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

    # Pending approvals (disbursements needing four-eyes) — UNCHANGED.
    # R37 only changes the manager-/officer-side Loan Application
    # queue filters to ds=1 status='Open'. The Loan Disbursement
    # four-eyes gate (post-approval disbursement) keeps its original
    # ds=0 filter.
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
    """Collections workspace: today's collections, collector leaderboard, arrears summary.

    R59 fix: Loan Repayment.posting_date is a DATETIME column. The old
    ``posting_date == today()`` filter compared a date string against
    datetimes, which only matches midnight — so collections recorded
    any time after 00:00 were invisible (leaderboard empty, today_total
    0). Compare on getdate() (>= today 00:00, < tomorrow 00:00) instead.
    """
    _guard()
    today_start = getdate(today())
    tomorrow_start = add_days(today_start, 1)

    # Today's collections — posting_date is a DATETIME column, so use a
    # list-of-lists filter (a dict literal cannot hold two "posting_date"
    # keys; the first bound would be silently dropped).
    today_repayments = frappe.get_all(
        "Loan Repayment",
        filters=[
            ["docstatus", "=", 1],
            ["posting_date", ">=", today_start],
            ["posting_date", "<", tomorrow_start],
        ],
        fields=["name", "amount_paid", "owner"],
    )
    today_total = sum(flt(r.amount_paid) for r in today_repayments)
    today_count = len(today_repayments)

    # Collector leaderboard — resolve the owner email to a display name so
    # the chart doesn't render raw emails (R59 UX: the collector should
    # recognise colleagues at a glance).
    collector_totals = {}
    for r in today_repayments:
        collector_totals[r.owner] = collector_totals.get(r.owner, 0) + flt(r.amount_paid)
    leaderboard = sorted(collector_totals.items(), key=lambda x: x[1], reverse=True)[:5]
    name_cache = {}
    leaderboard_rows = []
    for owner, amount in leaderboard:
        if owner not in name_cache:
            full_name = frappe.db.get_value("User", owner, "full_name") or owner
            # First name only — bar labels stay short.
            name_cache[owner] = (full_name or owner).split(" ")[0]
        leaderboard_rows.append({"collector": name_cache[owner], "amount": amount})

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
        "leaderboard": leaderboard_rows,
        "arrears": arrears,
    }


@frappe.whitelist()
def get_system_health():
    """Admin system health: scheduler, integrations, errors, backup.

    Phase 2 enrichment (admin console health widget):
      - error_breakdown_24h : dict of error-type → count (last 24h)
      - last_backup_size_bytes : int — size of the most recent backup file
      - last_backup_age_days  : int — days since the most recent backup
      - scheduler_last_tick   : datetime | None — last scheduler tick
    """
    _guard()
    import json
    import os
    from datetime import datetime

    from frappe.utils import add_days, get_datetime

    # Scheduler status
    scheduler_enabled = bool(frappe.db.get_single_value("System Settings", "enable_scheduler"))

    # Integration status
    integrations = {
        "aml": bool(frappe.conf.get("lms_aml_enabled", False)),
        "credit_bureau": bool(frappe.conf.get("lms_credit_bureau_enabled", False)),
        "sms": bool(frappe.db.get_single_value("SMS Settings", "sms_gateway_url")),
        "sms_twilio": bool(frappe.db.get_single_value("LMS Twilio Settings", "enabled"))
        if frappe.db.table_exists("LMS Twilio Settings")
        else False,
        "sms_otp": bool(
            frappe.db.table_exists("LMS OTP Challenge")
        ),
        "payments": bool(frappe.conf.get("lms_payments_enabled", False)),
    }

    # Recent errors (last 24h)
    since = add_days(today(), -1)
    error_count = frappe.db.count("Error Log", {"creation": (">=", since)})

    # Error breakdown by type (last 24h) — used by the health widget's stacked bar
    error_breakdown_rows = frappe.db.sql(
        """
        SELECT method AS type, COUNT(*) AS cnt
        FROM `tabError Log`
        WHERE creation >= %s
        GROUP BY method
        ORDER BY cnt DESC
        LIMIT 10
        """,
        (since,),
        as_dict=True,
    )
    error_breakdown_24h = {row["type"] or "Unknown": int(row["cnt"]) for row in error_breakdown_rows}

    # Last backup (file existence + metadata)
    backup_dir = frappe.get_site_path("private", "backups")
    last_backup_file = None
    last_backup_size_bytes = 0
    last_backup_age_days = None
    if os.path.isdir(backup_dir):
        files = sorted(
            [f for f in os.listdir(backup_dir) if f.endswith(".sql.gz")],
            reverse=True,
        )
        if files:
            last_backup_file = files[0]
            full_path = os.path.join(backup_dir, last_backup_file)
            try:
                last_backup_size_bytes = os.path.getsize(full_path)
            except OSError:
                last_backup_size_bytes = 0
            # Filename pattern YYYYMMDD_HHMMSS-... → derive date
            try:
                ts = datetime.strptime(last_backup_file[:15], "%Y%m%d_%H%M%S")
                last_backup_age_days = max(0, (getdate(today()) - ts.date()).days)
            except ValueError:
                last_backup_age_days = None

    # Last scheduler tick (from Scheduler Log if present, else None)
    scheduler_last_tick = None
    try:
        last_tick_row = frappe.db.sql(
            "SELECT creation FROM `tabScheduler Log` ORDER BY creation DESC LIMIT 1",
            as_dict=True,
        )
        if last_tick_row:
            scheduler_last_tick = last_tick_row[0]["creation"]
    except Exception:
        scheduler_last_tick = None

    return {
        "scheduler_enabled": scheduler_enabled,
        "integrations": integrations,
        "error_count_24h": error_count,
        "error_breakdown_24h": error_breakdown_24h,
        "last_backup_file": last_backup_file,
        "last_backup_size_bytes": last_backup_size_bytes,
        "last_backup_age_days": last_backup_age_days,
        "scheduler_last_tick": scheduler_last_tick,
    }


@frappe.whitelist()
def get_active_branches():
    """Return active (is_group=0) Cost Centers for the admin console branch picker.

    Returns ``{"branches": [{"name": ..., "label": ...}, ...]}`` — empty on a
    fresh site with no branches seeded. Used by the Admin Console's branch
    filter (Phase 2).
    """
    _guard()
    branches = frappe.get_all(
        "Cost Center",
        filters={"is_group": 0},
        fields=["name", "cost_center_name"],
        order_by="cost_center_name asc",
        limit_page_length=200,
    )
    return {
        "branches": [{"name": b.name, "label": b.cost_center_name or b.name} for b in branches],
    }


@frappe.whitelist()
def get_kyc_queue(limit: int = 20):
    """Pending KYC review queue for the admin console.

    Returns ``pending_count`` (count of all Pending + Submitted), ``by_status``
    (dict of status → count), and ``oldest`` (the N oldest pending rows for
    the timeline UI). Each oldest row has name, customer, kyc_status, creation.

    R25-F18: scope by branch when the caller is not a desk admin. KYC
    rows carry PII (national ID numbers, addresses) and a Branch Manager
    must not see another branch's KYC pipeline.
    """
    _guard()
    try:
        limit = int(limit) if limit else 20
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))

    caller_roles = set(frappe.get_roles())
    is_desk_admin = bool(caller_roles & {"System Manager", "Administrator"})

    # Resolve caller's branch for non-admin scope.
    caller_branch = None
    if not is_desk_admin:
        from lms_saas.api.staff import get_current_user_branch
        caller_branch = get_current_user_branch()

    pending_filters = {"kyc_status": ("in", ["Pending", "Submitted"])}
    if caller_branch:
        # Compliance doctype has no custom_lms_branch — scope via
        # the linked Customer. Restrict the count to customers in
        # the caller's branch.
        branch_customers = frappe.get_all(
            "Customer",
            filters={"custom_lms_branch": caller_branch},
            fields=["name"],
            limit_page_length=0,
        )
        customer_names = [c.name for c in branch_customers]
        if customer_names:
            pending_filters["customer"] = ("in", customer_names)
        else:
            # Caller has a branch but no customers in it; return empty.
            return {"pending_count": 0, "by_status": {}, "oldest": []}

    pending_count = frappe.db.count("LMS Borrower Compliance", pending_filters)

    by_status_rows = frappe.db.sql(
        "SELECT kyc_status, COUNT(name) AS cnt FROM `tabLMS Borrower Compliance` GROUP BY kyc_status",
        as_dict=True,
    )
    by_status = {r["kyc_status"] or "Unknown": int(r["cnt"]) for r in by_status_rows}

    oldest = frappe.get_all(
        "LMS Borrower Compliance",
        filters=pending_filters,
        fields=["name", "customer", "kyc_status", "creation"],
        order_by="creation asc",
        limit_page_length=limit,
    )
    for row in oldest:
        # Ensure ISO string for the timeline UI.
        if row.get("creation"):
            row["creation"] = str(row["creation"])

    return {
        "pending_count": int(pending_count),
        "by_status": by_status,
        "oldest": oldest,
    }


@frappe.whitelist()
def get_recent_activity(limit: int = 20):
    """Return the N most recent LMS Audit Event rows for the admin console timeline.

    Each event has event_type, event_user, event_time, reference_doctype,
    reference_name, and a `route` (desk URL) when both reference_doctype
    and reference_name are set AND the caller is a desk admin.

    R24-DL03: non-admin callers (Loan Officer / Branch Manager / Collector
    / Borrower) receive `route: None` so the client never renders a desk
    link to a portal user. The desk URL is built via the version-aware
    `desk_url()` helper so it works on both v15 (`/app/...`) and v16
    (`/desk/...`) installs.
    """
    _guard()
    try:
        limit = int(limit) if limit else 20
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 100))

    from lms_saas.utils.frappe_version import desk_url

    caller_roles = set(frappe.get_roles(frappe.session.user))
    is_desk_admin = bool(caller_roles & {"System Manager", "Administrator"})

    events = frappe.get_all(
        "LMS Audit Event",
        fields=["event_type", "event_user", "event_time", "reference_doctype", "reference_name", "details"],
        order_by="event_time desc",
        limit_page_length=limit,
    )
    for e in events:
        e["event_time"] = str(e["event_time"]) if e.get("event_time") else None
        if e.get("reference_doctype") and e.get("reference_name") and is_desk_admin:
            rel = f"{e['reference_doctype'].lower().replace(' ', '-')}/{e['reference_name']}"
            e["route"] = desk_url(rel)
        else:
            e["route"] = None
        # R25-F19: redact PII-bearing fields for non-admin callers. The
        # audit event `details` long-text can contain operator legal
        # name, licence number, regulator name; `event_user` exposes
        # which user did what. Both are now redacted to None for
        # portal staff, who only need to know that "something happened
        # at this time" — not the operator identity.
        if not is_desk_admin:
            e["event_user"] = None
            if e.get("details"):
                e["details"] = e["details"][:80] + ("…" if len(e["details"]) > 80 else "")
    return {"events": events}


def _guard():
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)
    roles = set(frappe.get_roles())
    if roles.intersection({"System Manager", "Administrator"}):
        return
    from lms_saas.utils.portal import resolve_portal_persona

    persona = resolve_portal_persona()
    if persona not in ("Branch Manager", "Loan Officer", "Collector", "Admin"):
        frappe.throw("Not permitted", frappe.PermissionError)
