"""Regulatory Hub addon API — report calendar, generation, archive, submissions.

Reuses existing report functions from ``api.manager`` and ``api.compliance``
for the actual report data. Stores generated reports in the new
``LMS Regulatory Submission`` doctype for archival and audit trail.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import (
    flt,
    today,
    add_days,
    add_to_date,
    getdate,
    now_datetime,
    formatdate,
)

from lms_saas.utils.addons import require_addon_persona


# ---------------------------------------------------------------------------
# Guards & helpers
# ---------------------------------------------------------------------------

def _require_regulatory():
    require_addon_persona("regulatory_hub")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _compliance_recipients() -> list[str]:
    """B-19: configured weekly KPI / compliance report recipients (site_config)."""
    raw = (frappe.conf.get("lms_compliance_report_recipients") or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


# ---------------------------------------------------------------------------
# Report Calendar
# ---------------------------------------------------------------------------

# Standard regulatory deadlines (can be extended via site_config)
REGULATORY_DEADLINES = [
    {
        "report_type": "Weekly KPI",
        "frequency": "Weekly",
        "due_day": "Monday",
        "description": _("Weekly KPI submission to regulator"),
    },
    {
        "report_type": "Portfolio At Risk",
        "frequency": "Monthly",
        "due_day": "5th of month",
        "description": _("Monthly PAR report"),
    },
    {
        "report_type": "Arrears Aging",
        "frequency": "Monthly",
        "due_day": "5th of month",
        "description": _("Monthly arrears aging report"),
    },
    {
        "report_type": "IFRS9 ECL",
        "frequency": "Quarterly",
        "due_day": "15th of quarter-end month",
        "description": _("Quarterly IFRS 9 ECL computation"),
    },
    {
        "report_type": "Transaction Summary",
        "frequency": "Monthly",
        "due_day": "5th of month",
        "description": _("Monthly transaction summary"),
    },
    {
        "report_type": "Complaint Summary",
        "frequency": "Monthly",
        "due_day": "5th of month",
        "description": _("Monthly complaint summary"),
    },
    {
        "report_type": "Incident Log",
        "frequency": "Monthly",
        "due_day": "5th of month",
        "description": _("Monthly incident log"),
    },
]


@frappe.whitelist()
def get_report_calendar(months_ahead=3):
    """Return upcoming regulatory deadlines for the next N months."""
    _require_regulatory()

    today_date = getdate(today())
    deadlines = []

    for offset in range(int(months_ahead)):
        target_month = add_to_date(today_date, months=offset)
        month_start = getdate(target_month.strftime("%Y-%m") + "-01")
        month_end = add_to_date(month_start, months=1, days=-1)

        for spec in REGULATORY_DEADLINES:
            # Compute due date within this month
            if spec["frequency"] == "Weekly":
                # First Monday of the month
                due = month_start
                while due.weekday() != 0:  # Monday
                    due = add_to_date(due, days=1)
                # All Mondays in the month
                while due <= month_end:
                    deadlines.append({
                        "report_type": spec["report_type"],
                        "frequency": spec["frequency"],
                        "due_date": formatdate(due, "yyyy-mm-dd"),
                        "description": spec["description"],
                        "is_overdue": due < today_date,
                        "is_due_soon": 0 <= (due - today_date).days <= 7,
                    })
                    due = add_to_date(due, days=7)
            elif spec["frequency"] == "Monthly":
                due_day = 5
                try:
                    due = getdate(target_month.strftime("%Y-%m") + f"-{due_day:02d}")
                except Exception:
                    continue
                deadlines.append({
                    "report_type": spec["report_type"],
                    "frequency": spec["frequency"],
                    "due_date": formatdate(due, "yyyy-mm-dd"),
                    "description": spec["description"],
                    "is_overdue": due < today_date,
                    "is_due_soon": 0 <= (due - today_date).days <= 7,
                })
            elif spec["frequency"] == "Quarterly":
                # 15th of quarter-end months: Mar, Jun, Sep, Dec
                if target_month.month in (3, 6, 9, 12):
                    due = getdate(target_month.strftime("%Y-%m") + "-15")
                    deadlines.append({
                        "report_type": spec["report_type"],
                        "frequency": spec["frequency"],
                        "due_date": formatdate(due, "yyyy-mm-dd"),
                        "description": spec["description"],
                        "is_overdue": due < today_date,
                        "is_due_soon": 0 <= (due - today_date).days <= 7,
                    })

    # Sort by due date
    deadlines.sort(key=lambda d: d["due_date"])
    return {"deadlines": deadlines}


# ---------------------------------------------------------------------------
# Report Generation
# ---------------------------------------------------------------------------

@frappe.whitelist()
def generate_report(report_type, period_start=None, period_end=None):
    """Generate a regulatory report by calling existing report functions.

    report_type: weekly_kpi | par | arrears | ecl | transaction_summary |
                 complaint_summary | incident_log
    """
    _require_regulatory()

    if not _is_admin():
        frappe.throw(_("Only administrators can generate regulatory reports."), frappe.PermissionError)

    period_start = period_start or formatdate(add_days(today(), -7), "yyyy-mm-dd")
    period_end = period_end or today()

    report_type_lower = (report_type or "").lower().replace(" ", "_")
    data = {}

    if report_type_lower in ("weekly_kpi", "weekly_kpi"):
        from lms_saas.api.compliance import get_sandbox_report
        data = get_sandbox_report(days=7)
        data["report_title"] = "Weekly KPI Report"

    elif report_type_lower == "par":
        from lms_saas.api.manager import get_portfolio_summary
        data = get_portfolio_summary()
        data["report_title"] = "Portfolio At Risk Report"

    elif report_type_lower == "arrears":
        from lms_saas.api.manager import get_arrears_aging_report
        data = get_arrears_aging_report(as_on_date=period_end)
        data["report_title"] = "Arrears Aging Report"

    elif report_type_lower == "ecl":
        # IFRS9 ECL — simplified computation from portfolio summary
        from lms_saas.api.manager import get_portfolio_summary
        summary = get_portfolio_summary().get("summary", {})
        # Simplified ECL: stage 1 (current) 1%, stage 2 (PAR30) 5%, stage 3 (PAR90) 50%
        ecl_stage1 = flt(summary.get("current_outstanding", 0)) * 0.01
        ecl_stage2 = flt(summary.get("par30_outstanding", 0)) * 0.05
        ecl_stage3 = flt(summary.get("par90_outstanding", 0)) * 0.50
        data = {
            "report_title": "IFRS9 ECL Report",
            "stage1": ecl_stage1,
            "stage2": ecl_stage2,
            "stage3": ecl_stage3,
            "total_ecl": ecl_stage1 + ecl_stage2 + ecl_stage3,
            "summary": summary,
        }

    elif report_type_lower == "transaction_summary":
        from lms_saas.api.manager import get_disbursement_report, get_collections_report
        disbursements = get_disbursement_report(from_date=period_start, to_date=period_end)
        collections = get_collections_report(from_date=period_start, to_date=period_end)
        data = {
            "report_title": "Transaction Summary",
            "disbursements": disbursements,
            "collections": collections,
        }

    elif report_type_lower == "complaint_summary":
        from lms_saas.api.compliance import get_sandbox_report
        sandbox = get_sandbox_report(days=30)
        data = {
            "report_title": "Complaint Summary",
            "complaints": sandbox.get("complaints", 0),
            "incident_log": sandbox.get("incident_log", []),
        }

    elif report_type_lower == "incident_log":
        incidents = frappe.get_all(
            "LMS Incident Log",
            filters={"reported_on": ("between", [period_start, period_end])},
            fields=["name", "incident_type", "severity", "status", "title", "reported_on"],
            order_by="reported_on desc",
        )
        data = {
            "report_title": "Incident Log",
            "incidents": incidents,
            "count": len(incidents),
        }

    else:
        frappe.throw(_("Unknown report type: {0}").format(report_type))

    data["report_type"] = report_type
    data["period_start"] = period_start
    data["period_end"] = period_end
    data["generated_on"] = now_datetime().isoformat()

    return data


# ---------------------------------------------------------------------------
# Report Archive
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_report_archive(status=None, limit=50):
    """List LMS Regulatory Submission records."""
    _require_regulatory()

    filters = {}
    if status:
        filters["status"] = status

    submissions = frappe.get_all(
        "LMS Regulatory Submission",
        filters=filters,
        fields=[
            "name", "report_type", "period_start", "period_end",
            "generated_on", "generated_by", "status", "file_attachment",
        ],
        order_by="generated_on desc",
        limit_page_length=int(limit),
    )
    return {"submissions": submissions}


@frappe.whitelist()
def save_submission(report_type, period_start, period_end, status="Draft", notes=None, file_attachment=None):
    """Store a generated report as an LMS Regulatory Submission record."""
    _require_regulatory()

    if not _is_admin():
        frappe.throw(_("Only administrators can save regulatory submissions."), frappe.PermissionError)

    doc = frappe.new_doc("LMS Regulatory Submission")
    doc.report_type = report_type
    doc.period_start = period_start
    doc.period_end = period_end
    doc.generated_on = now_datetime()
    doc.generated_by = frappe.session.user
    doc.status = status
    doc.notes = notes
    if file_attachment:
        doc.file_attachment = file_attachment
    doc.flags.ignore_permissions = True
    doc.insert()
    return {"name": doc.name, "status": doc.status}


# ---------------------------------------------------------------------------
# Regulatory Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_regulatory_stats():
    """Summary stats for the regulatory hub dashboard."""
    _require_regulatory()

    total = frappe.db.count("LMS Regulatory Submission")
    draft = frappe.db.count("LMS Regulatory Submission", {"status": "Draft"})
    submitted = frappe.db.count("LMS Regulatory Submission", {"status": "Submitted"})
    acknowledged = frappe.db.count("LMS Regulatory Submission", {"status": "Acknowledged"})

    # Upcoming deadlines (next 7 days)
    calendar = get_report_calendar(months_ahead=1)
    upcoming = [d for d in calendar.get("deadlines", []) if d.get("is_due_soon")]
    overdue = [d for d in calendar.get("deadlines", []) if d.get("is_overdue")]

    recipients = _compliance_recipients()

    return {
        "total_submissions": total,
        "draft": draft,
        "submitted": submitted,
        "acknowledged": acknowledged,
        "upcoming_deadlines": len(upcoming),
        "overdue_deadlines": len(overdue),
        "pending_submissions": draft,
        "is_admin": _is_admin(),
        "compliance_recipients": recipients,
        "recipients_configured": bool(recipients),
    }


@frappe.whitelist()
def get_branch_summary():
    """Read-only Branch Manager surface: pending drafts + upcoming deadlines.

    Write actions (generate/save) remain admin-only via those endpoints.
    """
    _require_regulatory()

    stats = get_regulatory_stats()
    calendar = get_report_calendar(months_ahead=1)
    due_soon = [d for d in calendar.get("deadlines", []) if d.get("is_due_soon")]
    overdue = [d for d in calendar.get("deadlines", []) if d.get("is_overdue")]

    pending = int(stats.get("draft") or 0)
    return {
        "pending_submissions": pending,
        "upcoming_deadlines": len(due_soon),
        "overdue_deadlines": len(overdue),
        "due_soon": due_soon[:5],
        "overdue": overdue[:5],
        "compliance_recipients": stats.get("compliance_recipients") or [],
        "recipients_configured": stats.get("recipients_configured"),
        "is_admin": stats.get("is_admin"),
        "summary_line": _(
            "Your organisation has {0} draft submission(s) awaiting admin filing."
        ).format(pending),
    }