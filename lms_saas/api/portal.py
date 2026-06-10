import frappe
from frappe.utils import flt, getdate, get_url, today
from frappe.utils.data import add_to_date, formatdate

from lms_saas.utils.calculations import remaining_payable


@frappe.whitelist()
def get_my_loans():
    customer = _require_customer()
    loans = frappe.get_all(
        "Loan",
        filters={
            "applicant_type": "Customer",
            "applicant": customer,
            "docstatus": 1,
        },
        fields=[
            "name",
            "loan_amount",
            "status",
            "days_past_due",
            "custom_days_past_due",
            "rate_of_interest",
            "disbursed_amount",
            "total_payment",
            "total_amount_paid",
        ],
        order_by="modified desc",
    )
    total_outstanding = 0
    active_count = 0
    bucket_totals = {"current": 0, "par30": 0, "par60": 0, "par90": 0}

    for loan in loans:
        loan["dpd"] = loan.custom_days_past_due or loan.days_past_due or 0
        # Borrower-facing outstanding = remaining payable (principal + interest)
        # net of what has already been paid. total_payment is the full payable.
        loan["outstanding"] = remaining_payable(loan.total_payment, loan.total_amount_paid)
        total_outstanding += loan["outstanding"]
        dpd = flt(loan["dpd"])
        if dpd > 90:
            bucket_totals["par90"] += loan["outstanding"]
        elif dpd > 60:
            bucket_totals["par60"] += loan["outstanding"]
        elif dpd > 30:
            bucket_totals["par30"] += loan["outstanding"]
        else:
            bucket_totals["current"] += loan["outstanding"]
        if loan.status in ("Disbursed", "Active", "Partially Disbursed"):
            active_count += 1

    loan_ids = [loan.name for loan in loans]
    next_due = _earliest_next_payment(loan_ids) if loans else None
    schedule_rows = _schedule_rows_for_loans(loan_ids)

    return {
        "loans": loans,
        "summary": {
            "total_outstanding": total_outstanding,
            "active_count": active_count,
            "loan_count": len(loans),
            "next_due": next_due,
            "at_risk_count": len([loan for loan in loans if flt(loan.get("dpd")) > 30]),
            "delinquency_ratio": (bucket_totals["par30"] + bucket_totals["par60"] + bucket_totals["par90"])
            / total_outstanding
            if total_outstanding
            else 0,
        },
        "dashboard": {
            "bucket_totals": bucket_totals,
            "upcoming_due": _monthly_due_projection(schedule_rows),
            "loan_mix": _loan_mix(loans),
        },
    }


@frappe.whitelist()
def get_loan_detail(loan_id):
    customer = _require_customer()
    loan = frappe.get_doc("Loan", loan_id)
    if loan.applicant != customer or loan.applicant_type != "Customer":
        frappe.throw("Not permitted", frappe.PermissionError)

    schedule = []
    schedule_docs = frappe.get_all(
        "Loan Repayment Schedule",
        filters={"loan": loan_id, "docstatus": 1},
        pluck="name",
    )
    for parent in schedule_docs:
        rows = frappe.get_all(
            "Repayment Schedule",
            filters={"parent": parent, "parenttype": "Loan Repayment Schedule"},
            fields=["payment_date", "total_payment", "principal_amount", "interest_amount", "balance_loan_amount"],
            order_by="payment_date asc",
        )
        schedule.extend(rows)

    repayments = frappe.get_all(
        "Loan Repayment",
        filters={"against_loan": loan_id, "docstatus": 1},
        fields=["name", "posting_date", "amount_paid"],
        order_by="posting_date desc",
    )

    today_date = getdate(today())
    for row in schedule:
        due = getdate(row.payment_date) if row.payment_date else None
        if not due:
            row["schedule_state"] = "unknown"
        elif due < today_date:
            row["schedule_state"] = "past"
        elif due == today_date:
            row["schedule_state"] = "due_today"
        else:
            row["schedule_state"] = "upcoming"

    return {
        "loan": loan.as_dict(),
        "schedule": schedule,
        "repayments": repayments,
        "outstanding": remaining_payable(loan.total_payment, loan.total_amount_paid),
        "next_payment": _next_schedule_payment(loan_id),
        "dpd": loan.custom_days_past_due or loan.days_past_due or 0,
    }


def _schedule_rows_for_loans(loan_ids):
    if not loan_ids:
        return []
    schedule_docs = frappe.get_all(
        "Loan Repayment Schedule",
        filters={"loan": ["in", loan_ids], "docstatus": 1},
        fields=["name", "loan"],
    )
    if not schedule_docs:
        return []
    parent_map = {row.name: row.loan for row in schedule_docs}
    rows = frappe.get_all(
        "Repayment Schedule",
        filters={
            "parent": ["in", list(parent_map.keys())],
            "parenttype": "Loan Repayment Schedule",
        },
        fields=["parent", "payment_date", "total_payment"],
        order_by="payment_date asc",
    )
    for row in rows:
        row["loan"] = parent_map.get(row.parent)
    return rows


def _earliest_next_payment(loan_ids):
    """Earliest schedule line on or after today across loans."""
    today_date = getdate(today())
    candidates = _schedule_rows_for_loans(loan_ids)
    upcoming = [
        row for row in candidates if row.payment_date and getdate(row.payment_date) >= today_date
    ]
    if upcoming:
        upcoming.sort(key=lambda r: (r.payment_date, r.loan or ""))
        return upcoming[0]
    return candidates[0] if candidates else None


def _next_schedule_payment(loan_id):
    return _earliest_next_payment([loan_id])


def _monthly_due_projection(schedule_rows, months=6):
    """Aggregate future scheduled dues per month for chart-like widgets."""
    month_totals = {}
    today_date = getdate(today())
    for offset in range(months):
        dt = add_to_date(today_date, months=offset)
        key = dt.strftime("%Y-%m")
        month_totals[key] = 0

    for row in schedule_rows or []:
        if not row.get("payment_date"):
            continue
        due_date = getdate(row.payment_date)
        month_key = due_date.strftime("%Y-%m")
        if month_key in month_totals:
            month_totals[month_key] += flt(row.get("total_payment"))

    return [{"label": formatdate(f"{month}-01", "MMM yyyy"), "value": flt(value)} for month, value in month_totals.items()]


def _loan_mix(loans):
    data = {"current": 0, "watchlist": 0, "npa": 0}
    for loan in loans or []:
        dpd = flt(loan.get("dpd"))
        if dpd > 90:
            data["npa"] += 1
        elif dpd > 30:
            data["watchlist"] += 1
        else:
            data["current"] += 1
    return data


@frappe.whitelist()
def get_statement_pdf(loan_id):
    customer = _require_customer()
    loan = frappe.get_doc("Loan", loan_id)
    if loan.applicant != customer or loan.applicant_type != "Customer":
        frappe.throw("Not permitted", frappe.PermissionError)

    print_format = frappe.db.get_value("Print Format", {"doc_type": "Loan", "name": "LMS Loan Statement"}, "name")
    if not print_format:
        frappe.throw("Print Format 'LMS Loan Statement' not found. Run bench migrate.")

    pdf = frappe.get_print("Loan", loan_id, print_format=print_format, as_pdf=True)
    frappe.local.response.filename = f"statement_{loan_id}.pdf"
    frappe.local.response.filecontent = pdf
    frappe.local.response.type = "download"
    return {"url": get_url(f"/api/method/lms_saas.api.portal.download_statement&loan_id={loan_id}")}


def _require_customer():
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)

    from lms_saas.permissions import _portal_customer

    linked = _portal_customer(frappe.session.user)
    if not linked:
        frappe.throw("No Customer linked to your portal account.", frappe.PermissionError)
    return linked


@frappe.whitelist()
def get_portal_shell():
    """Branding + nav state for legacy website pages (password reset, edit profile)."""
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)

    from lms_saas.utils.brand import get_portal_brand
    from lms_saas.utils.portal import show_staff_desk_link

    brand = get_portal_brand()
    path = (frappe.local.path or "").strip("/")
    nav_active = "account" if path.startswith("lms/account") or path.startswith("update-") else "loans"
    if path.startswith("lms/apply"):
        nav_active = "apply"
    elif path.startswith("lms/pay"):
        nav_active = "pay"
    return {
        "brand": brand,
        "nav_active": nav_active,
        "show_staff_desk": show_staff_desk_link(),
        "payments_enabled": bool(frappe.conf.get("lms_payments_enabled", False)),
    }


@frappe.whitelist()
def submit_loan_application(loan_amount, loan_product=None, repayment_periods=6):
    """Borrower self-service loan application (draft, desk review required)."""
    customer = _require_customer()

    if not frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "consent_given"):
        frappe.throw("Customer consent is required before applying.")

    company = frappe.db.get_single_value("Global Defaults", "default_company")
    if not loan_product:
        loan_product = frappe.db.get_value("Loan Product", {"company": company, "product_code": "LMS-STD"}, "name")

    app = frappe.get_doc(
        {
            "doctype": "Loan Application",
            "applicant_type": "Customer",
            "applicant": customer,
            "company": company,
            "loan_product": loan_product,
            "loan_amount": flt(loan_amount),
            "repayment_periods": int(repayment_periods),
            "rate_of_interest": frappe.db.get_value("Loan Product", loan_product, "rate_of_interest") or 0,
        }
    )
    app.insert(ignore_permissions=True)

    try:
        from lms_saas.api.webhooks import dispatch_webhook_event

        dispatch_webhook_event("loan.application.submitted", {"application": app.name, "customer": customer})
    except Exception:
        pass

    return {"application": app.name, "status": "Draft"}


@frappe.whitelist()
def upload_kyc_document(file_url, fieldname="id_document_proof"):
    """Attach KYC document to borrower compliance record."""
    customer = _require_customer()
    compliance_name = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
    if not compliance_name:
        frappe.throw("Compliance profile not found. Contact your loan officer.")

    allowed = {"id_document_proof", "proof_of_address"}
    if fieldname not in allowed:
        frappe.throw("Invalid document field")

    frappe.db.set_value("LMS Borrower Compliance", compliance_name, fieldname, file_url)
    return {"compliance": compliance_name, "field": fieldname, "file_url": file_url}


@frappe.whitelist()
def initiate_repayment(loan_id, amount, provider_code="ecocash"):
    """Start online repayment for a loan."""
    customer = _require_customer()
    loan = frappe.get_doc("Loan", loan_id)
    if loan.applicant != customer or loan.applicant_type != "Customer":
        frappe.throw("Not permitted", frappe.PermissionError)

    from lms_saas.api.payments.service import create_payment_intent

    return create_payment_intent(loan=loan_id, amount=flt(amount), provider_code=provider_code)


@frappe.whitelist()
def get_apply_context():
    """Loan products and compliance state for apply form."""
    customer = _require_customer()
    company = frappe.db.get_single_value("Global Defaults", "default_company")
    products = frappe.get_all(
        "Loan Product",
        filters={"company": company, "disabled": 0},
        fields=["name", "product_name", "rate_of_interest", "maximum_loan_amount"],
    )
    compliance = frappe.db.get_value(
        "LMS Borrower Compliance",
        {"customer": customer},
        ["name", "kyc_status", "consent_given", "id_document_proof", "proof_of_address"],
        as_dict=True,
    )
    return {"products": products, "compliance": compliance, "customer": customer}
