"""Customer Feedback addon API — surveys, responses, NPS, dashboards.

Uses the new ``LMS Survey``, ``LMS Survey Question``, ``LMS Survey Response``,
and ``LMS Survey Response Item`` doctypes. Borrowers take surveys and view
their responses; managers see aggregate dashboards and recent feedback.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, now_datetime, today

from lms_saas.utils.addons import require_addon_persona


# ---------------------------------------------------------------------------
# Guards & helpers
# ---------------------------------------------------------------------------

def _require_feedback():
    require_addon_persona("customer_feedback")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


def _current_customer():
    """Resolve the Customer linked to the current user (for borrowers)."""
    from lms_saas.permissions import _portal_customer
    return _portal_customer(frappe.session.user)


def _is_borrower():
    from lms_saas.utils.portal import is_portal_borrower
    return is_portal_borrower()


# ---------------------------------------------------------------------------
# Surveys
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_surveys(limit=50):
    """List active LMS Survey records.

    Borrowers see active surveys they haven't yet responded to.
    Staff see all surveys.
    """
    _require_feedback()

    filters = {}
    if _is_borrower():
        filters["is_active"] = 1

    surveys = frappe.get_all(
        "LMS Survey",
        filters=filters,
        fields=["name", "title", "description", "trigger_event", "is_active"],
        order_by="creation desc",
        limit_page_length=int(limit),
    )

    # Enrich with question count
    for survey in surveys:
        survey["question_count"] = frappe.db.count(
            "LMS Survey Question",
            {"parent": survey["name"], "parenttype": "LMS Survey"},
        )
        if _is_borrower():
            # Check if borrower already responded
            customer = _current_customer()
            if customer:
                survey["responded"] = bool(frappe.db.exists(
                    "LMS Survey Response",
                    {"survey": survey["name"], "customer": customer},
                ))
            else:
                survey["responded"] = False

    return {"surveys": surveys}


@frappe.whitelist()
def get_survey_detail(survey_name):
    """Return a single survey with its questions."""
    _require_feedback()

    if not frappe.db.exists("LMS Survey", survey_name):
        frappe.throw(_("Survey {0} not found.").format(survey_name))

    survey = frappe.get_doc("LMS Survey", survey_name)
    questions = []
    for q in survey.questions:
        questions.append({
            "name": q.name,
            "question_text": q.question_text,
            "question_type": q.question_type,
            "options": q.options.split("\n") if q.options else [],
        })

    return {
        "name": survey.name,
        "title": survey.title,
        "description": survey.description,
        "trigger_event": survey.trigger_event,
        "is_active": survey.is_active,
        "questions": questions,
    }


# ---------------------------------------------------------------------------
# Survey Responses
# ---------------------------------------------------------------------------

@frappe.whitelist()
def submit_survey_response(survey_name, responses, loan=None, nps_score=None):
    """Borrower submits survey answers.

    responses: JSON string of [{question: "...", answer: "..."}, ...]
    """
    _require_feedback()

    import json

    if not frappe.db.exists("LMS Survey", survey_name):
        frappe.throw(_("Survey {0} not found.").format(survey_name))

    customer = _current_customer()
    if not customer:
        frappe.throw(_("No borrower profile linked to your account."), frappe.PermissionError)

    # Check for duplicate response
    existing = frappe.db.exists("LMS Survey Response", {"survey": survey_name, "customer": customer})
    if existing:
        frappe.throw(_("You have already responded to this survey."))

    if isinstance(responses, str):
        responses = json.loads(responses)

    doc = frappe.new_doc("LMS Survey Response")
    doc.survey = survey_name
    doc.customer = customer
    doc.loan = loan
    doc.submitted_by = frappe.session.user
    doc.submitted_on = now_datetime()
    if nps_score is not None:
        doc.nps_score = int(nps_score)

    for resp in responses:
        doc.append("responses", {
            "question": resp.get("question", ""),
            "answer": str(resp.get("answer", "")),
        })

    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "message": _("Survey response submitted. Thank you!")}


@frappe.whitelist()
def get_feedback_list(limit=50):
    """Return recent survey responses (staff view)."""
    _require_feedback()

    if _is_borrower():
        # Borrower sees their own responses
        customer = _current_customer()
        if not customer:
            return {"responses": []}
        filters = {"customer": customer}
    else:
        filters = {}

    responses = frappe.get_all(
        "LMS Survey Response",
        filters=filters,
        fields=["name", "survey", "customer", "loan", "submitted_by",
                "submitted_on", "nps_score"],
        order_by="submitted_on desc",
        limit_page_length=int(limit),
    )

    for resp in responses:
        resp["survey_title"] = frappe.db.get_value("LMS Survey", resp["survey"], "title") if resp.get("survey") else ""
        resp["customer_name"] = frappe.db.get_value("Customer", resp["customer"], "customer_name") if resp.get("customer") else ""

    return {"responses": responses}


# ---------------------------------------------------------------------------
# Feedback Dashboard
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_feedback_dashboard():
    """Aggregate scores by branch/officer/product (manager view)."""
    _require_feedback()

    if _is_borrower():
        frappe.throw(_("Not permitted"), frappe.PermissionError)

    # Get all survey responses
    responses = frappe.get_all(
        "LMS Survey Response",
        filters={},
        fields=["name", "survey", "customer", "loan", "nps_score", "submitted_on"],
        limit_page_length=0,
    )

    # Aggregate by survey
    by_survey = {}
    by_branch = {}
    by_officer = {}
    nps_scores = []

    for resp in responses:
        # By survey
        survey_title = frappe.db.get_value("LMS Survey", resp["survey"], "title") if resp.get("survey") else "Unknown"
        if survey_title not in by_survey:
            by_survey[survey_title] = {"count": 0, "nps_sum": 0, "nps_count": 0}
        by_survey[survey_title]["count"] += 1
        if resp.get("nps_score") is not None:
            by_survey[survey_title]["nps_sum"] += int(resp["nps_score"])
            by_survey[survey_title]["nps_count"] += 1
            nps_scores.append(int(resp["nps_score"]))

        # By branch (via loan)
        if resp.get("loan"):
            loan_data = frappe.db.get_value(
                "Loan", resp["loan"],
                ["custom_lms_branch", "custom_loan_officer"],
                as_dict=True,
            )
            if loan_data:
                branch = loan_data.get("custom_lms_branch") or "Unassigned"
                if branch not in by_branch:
                    by_branch[branch] = {"count": 0, "nps_sum": 0, "nps_count": 0}
                by_branch[branch]["count"] += 1
                if resp.get("nps_score") is not None:
                    by_branch[branch]["nps_sum"] += int(resp["nps_score"])
                    by_branch[branch]["nps_count"] += 1

                officer = loan_data.get("custom_loan_officer") or "Unassigned"
                officer_name = frappe.db.get_value("Employee", officer, "employee_name") if officer != "Unassigned" else "Unassigned"
                if officer not in by_officer:
                    by_officer[officer] = {"officer_name": officer_name, "count": 0, "nps_sum": 0, "nps_count": 0}
                by_officer[officer]["count"] += 1
                if resp.get("nps_score") is not None:
                    by_officer[officer]["nps_sum"] += int(resp["nps_score"])
                    by_officer[officer]["nps_count"] += 1

    # Compute averages
    for survey_title, data in by_survey.items():
        data["avg_nps"] = flt(data["nps_sum"] / data["nps_count"]) if data["nps_count"] else 0
    for branch, data in by_branch.items():
        data["avg_nps"] = flt(data["nps_sum"] / data["nps_count"]) if data["nps_count"] else 0
    for officer, data in by_officer.items():
        data["avg_nps"] = flt(data["nps_sum"] / data["nps_count"]) if data["nps_count"] else 0

    # Overall NPS
    overall_nps = 0
    if nps_scores:
        promoters = sum(1 for s in nps_scores if s >= 9)
        detractors = sum(1 for s in nps_scores if s <= 6)
        overall_nps = flt((promoters - detractors) / len(nps_scores) * 100)

    return {
        "total_responses": len(responses),
        "overall_nps": overall_nps,
        "by_survey": [{"survey": k, **v} for k, v in by_survey.items()],
        "by_branch": [{"branch": k, **v} for k, v in by_branch.items()],
        "by_officer": [{"officer": k, **v} for k, v in by_officer.items()],
    }


# ---------------------------------------------------------------------------
# Survey Creation (admin)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def create_survey(title, description=None, trigger_event="Manual", questions=None):
    """Admin creates a survey with questions.

    questions: JSON string of [{question_text, question_type, options}, ...]
    """
    _require_feedback()

    if not _is_admin():
        frappe.throw(_("Only administrators can create surveys."), frappe.PermissionError)

    import json

    if isinstance(questions, str):
        questions = json.loads(questions)

    doc = frappe.new_doc("LMS Survey")
    doc.title = title
    doc.description = description
    doc.trigger_event = trigger_event
    doc.is_active = 1

    for q in questions or []:
        doc.append("questions", {
            "question_text": q.get("question_text", ""),
            "question_type": q.get("question_type", "Rating"),
            "options": q.get("options", ""),
        })

    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "title": doc.title}