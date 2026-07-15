"""Recruitment addon API — job openings, applicants, interviews, staffing.

Reuses HRMS doctypes: Job Opening, Job Applicant, Interview, Staffing Plan.
Branch-scoped via Department / Branch on Job Opening.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import today, getdate, now_datetime, add_days

from lms_saas.utils.addons import require_addon_persona


def _require_recruitment():
    require_addon_persona("recruitment")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _branch_employees(branch=None):
    """Return Employee names for the given branch (or current user's branch)."""
    branch = branch or _branch()
    if not branch:
        return []

    meta = frappe.get_meta("Employee")
    filters = {"status": "Active"}
    for field in ("branch", "cost_center", "custom_lms_branch"):
        if meta.has_field(field):
            filters[field] = branch
            break
    return frappe.get_all("Employee", filters=filters, pluck="name")


# ---------------------------------------------------------------------------
# Job Openings
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_job_openings(status=None, limit=100):
    """List open job positions (branch-scoped for non-admins)."""
    _require_recruitment()

    filters = {"status": ["in", ["Open", "Published"]]}

    # Branch scoping via the 'branch' or 'custom_lms_branch' field on Job Opening
    branch = _branch()
    if branch and not _is_admin():
        meta = frappe.get_meta("Job Opening")
        for field in ("branch", "custom_lms_branch", "department"):
            if meta.has_field(field):
                filters[field] = branch
                break

    if status:
        filters["status"] = status

    openings = frappe.get_all(
        "Job Opening",
        filters=filters,
        fields=["name", "job_title", "status", "posted_on", "description",
                "company", "department", "designation", "vacancies",
                "closes_on"],
        order_by="posted_on desc",
        limit_page_length=int(limit),
    )

    # Attach applicant counts
    for op in openings:
        op["applicant_count"] = frappe.db.count("Job Applicant", {
            "job_title": op["name"],
        })

    return {"openings": openings}


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_applicants(job_opening=None, limit=100):
    """List applicants per job opening (or all branch applicants)."""
    _require_recruitment()

    filters = {}
    if job_opening:
        filters["job_title"] = job_opening

    applicants = frappe.get_all(
        "Job Applicant",
        filters=filters,
        fields=["name", "applicant_name", "email_id", "phone_number",
                "status", "job_title", "cover_letter", "resume_link",
                "creation"],
        order_by="creation desc",
        limit_page_length=int(limit),
    )
    return {"applicants": applicants}


@frappe.whitelist()
def get_applicant_detail(applicant_name):
    """Return a single applicant with interview history."""
    _require_recruitment()

    applicant = frappe.get_doc("Job Applicant", applicant_name)

    # Interview history
    interviews = frappe.get_all(
        "Interview",
        filters={"job_applicant": applicant_name},
        fields=["name", "interview_round", "scheduled_on", "status",
                "rating", "interview_feedback", "designation"],
        order_by="scheduled_on desc",
        limit=20,
    )

    return {
        "applicant": {
            "name": applicant.name,
            "applicant_name": applicant.applicant_name,
            "email_id": applicant.email_id,
            "phone_number": applicant.phone_number,
            "status": applicant.status,
            "job_title": applicant.job_title,
            "cover_letter": applicant.cover_letter,
            "resume_link": applicant.resume_link,
            "creation": applicant.creation,
        },
        "interviews": interviews,
    }


# ---------------------------------------------------------------------------
# Interviews
# ---------------------------------------------------------------------------

@frappe.whitelist()
def schedule_interview(applicant_name, interview_round, scheduled_on,
                       interviewers=None, designation=None):
    """Create an interview round for a job applicant."""
    _require_recruitment()

    import json

    doc = frappe.new_doc("Interview")
    doc.job_applicant = applicant_name
    doc.interview_round = interview_round
    doc.scheduled_on = scheduled_on
    if designation:
        doc.designation = designation

    # Parse interviewers
    if interviewers:
        if isinstance(interviewers, str):
            try:
                interviewers = json.loads(interviewers)
            except (json.JSONDecodeError, ValueError):
                interviewers = [s.strip() for s in interviewers.split(",") if s.strip()]
        if isinstance(interviewers, list):
            for interviewer in interviewers:
                doc.append("interview_details", {
                    "interviewer": interviewer,
                })

    doc.flags.ignore_permissions = True
    doc.insert()
    return {"name": doc.name, "scheduled_on": scheduled_on}


# ---------------------------------------------------------------------------
# Staffing Plan
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_staffing_plan():
    """Return branch staffing plan vs actual headcount."""
    _require_recruitment()

    branch = _branch()
    employees = _branch_employees()
    actual_count = len(employees)

    # Active staffing plans
    filters = {"docstatus": 1}
    meta = frappe.get_meta("Staffing Plan")
    if branch and meta.has_field("branch"):
        filters["branch"] = branch

    plans = frappe.get_all(
        "Staffing Plan",
        filters=filters,
        fields=["name", "from_date", "to_date", "company", "branch",
                "total_estimated_budget"],
        order_by="from_date desc",
        limit=5,
    )

    # Get staffing plan details (sub-table)
    for plan in plans:
        details = frappe.get_all(
            "Staffing Plan Detail",
            filters={"parent": plan["name"]},
            fields=["name", "designation", "no_of_positions", "estimated_cost_per_position",
                    "vacancies", "estimated_cost"],
            limit=50,
        )
        plan["details"] = details
        plan["planned_positions"] = sum((d.get("no_of_positions") or 0) for d in details)
        plan["open_vacancies"] = sum((d.get("vacancies") or 0) for d in details)

    return {
        "plans": plans,
        "actual_headcount": actual_count,
        "branch": branch,
    }