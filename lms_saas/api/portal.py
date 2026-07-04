import frappe
from frappe.utils import flt, getdate, get_url, today
from frappe.utils.data import add_to_date, formatdate

from lms_saas.utils.calculations import remaining_payable
from lms_saas.utils.rate_limit import rate_limit


@frappe.whitelist()
def get_my_loans(limit_start=0, limit_page_length=20):
    customer = _require_customer(raise_exception=False)
    if not customer:
        return {
            "loans": [],
            "summary": {
                "total_outstanding": 0,
                "active_count": 0,
                "loan_count": 0,
                "next_due": None,
                "at_risk_count": 0,
                "delinquency_ratio": 0,
                "outstanding_history": [],
            },
            "dashboard": {
                "bucket_totals": {"current": 0, "par30": 0, "par60": 0, "par90": 0},
                "upcoming_due": [],
                "loan_mix": {"current": 0, "watchlist": 0, "npa": 0},
                "collections_trend": [],
                "outstanding_history": [],
            },
            "total_count": 0,
            "no_customer_linked": 1,
        }
    limit_start = int(limit_start)
    limit_page_length = int(limit_page_length)
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
        limit_start=limit_start,
        limit_page_length=limit_page_length,
    )
    total_count = frappe.db.count(
        "Loan",
        {
            "applicant_type": "Customer",
            "applicant": customer,
            "docstatus": 1,
        },
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
    collections_trend = _collections_trend(customer) if loans else []
    outstanding_history = _outstanding_history(customer) if loans else []
    outstanding_delta = _outstanding_delta(outstanding_history) if outstanding_history else None

    summary_out = {
        "total_outstanding": total_outstanding,
        "active_count": active_count,
        "loan_count": len(loans),
        "next_due": next_due,
        "at_risk_count": len([loan for loan in loans if flt(loan.get("dpd")) > 30]),
        "delinquency_ratio": (bucket_totals["par30"] + bucket_totals["par60"] + bucket_totals["par90"])
        / total_outstanding
        if total_outstanding
        else 0,
        "outstanding_history": outstanding_history,
    }
    if outstanding_delta is not None:
        summary_out["outstanding_delta"] = outstanding_delta

    return {
        "loans": loans,
        "summary": summary_out,
        "dashboard": {
            "bucket_totals": bucket_totals,
            "upcoming_due": _monthly_due_projection(schedule_rows),
            "loan_mix": _loan_mix(loans),
            "collections_trend": collections_trend,
            "outstanding_history": outstanding_history,
        },
        "total_count": total_count,
    }


def _collections_trend(customer, months=6):
    """Sum of repayments per month, last `months` months, for the borrower."""
    if not customer:
        return []
    today_date = getdate(today())
    bucket_keys = []
    for offset in range(months - 1, -1, -1):
        dt = add_to_date(today_date, months=-offset)
        bucket_keys.append(dt.strftime("%Y-%m"))
    bucket = {k: 0.0 for k in bucket_keys}

    rows = frappe.db.sql(
        """
        SELECT post.posting_date, SUM(post.amount_paid) AS total
        FROM `tabLoan Repayment` post
        INNER JOIN `tabLoan` loan ON loan.name = post.against_loan
        WHERE loan.applicant_type = 'Customer'
          AND loan.applicant = %(customer)s
          AND post.docstatus = 1
          AND post.posting_date >= DATE_SUB(%(today)s, INTERVAL %(months)s MONTH)
        GROUP BY post.posting_date
        """,
        {"customer": customer, "today": today_date, "months": months},
        as_dict=True,
    )
    for r in rows:
        if not r.posting_date:
            continue
        k = getdate(r.posting_date).strftime("%Y-%m")
        if k in bucket:
            bucket[k] += flt(r.total)

    return [
        {"label": formatdate(f"{k}-01", "MMM yyyy"), "value": flt(bucket[k])}
        for k in bucket_keys
    ]


def _outstanding_history(customer, months=6):
    """Synthesize an outstanding-history series: today's outstanding + previous
    months' cumulative repayments (used as a sparkline for the KPI hero)."""
    if not customer:
        return []
    trend = _collections_trend(customer, months=months)
    return [r.get("value", 0) for r in trend]


def _outstanding_delta(history):
    """% change between the first and last values of a history series."""
    if not history or len(history) < 2:
        return None
    first = flt(history[0])
    last = flt(history[-1])
    if first <= 0:
        return 0
    return round(((last - first) / first) * 100, 1)


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
        "collateral": _get_loan_collateral(loan),
    }


def _get_loan_collateral(loan):
    """Return collateral summary for a loan (borrower-facing)."""
    try:
        from lms_saas.api.collateral import get_collateral_coverage

        coverage = get_collateral_coverage(loan)
        return {
            "items": coverage.get("items", []),
            "total_net_realizable_value": coverage.get("total_net_realizable_value", 0),
            "total_allocated_value": coverage.get("total_allocated_value", 0),
            "coverage_ratio": coverage.get("coverage_ratio", 0),
        }
    except Exception:
        return {"items": [], "total_net_realizable_value": 0, "total_allocated_value": 0, "coverage_ratio": 0}


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


def _require_customer(raise_exception=True):
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)

    from lms_saas.permissions import _portal_customer

    linked = _portal_customer(frappe.session.user)
    if not linked:
        if raise_exception:
            frappe.throw("No Customer linked to your portal account.", frappe.PermissionError)
        return None
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
@rate_limit(max_calls=5, window_seconds=60)
def submit_loan_application(loan_amount, loan_product=None, repayment_periods=6):
    """Borrower self-service loan application (draft, desk review required)."""
    customer = _require_customer()

    compliance = frappe.db.get_value(
        "LMS Borrower Compliance",
        {"customer": customer},
        ["consent_given", "id_document_proof", "proof_of_address"],
        as_dict=True,
    )
    if not compliance or not compliance.get("consent_given"):
        frappe.throw("Customer consent is required before applying.")

    # Require KYC documents so desk review isn't blocked on missing uploads.
    missing = []
    if not compliance.get("id_document_proof"):
        missing.append("ID document")
    if not compliance.get("proof_of_address"):
        missing.append("Proof of address")
    if missing:
        frappe.throw(
            "Please upload the following document(s) before submitting: "
            + ", ".join(missing) + "."
        )

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
@rate_limit(max_calls=10, window_seconds=60)
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
@rate_limit(max_calls=10, window_seconds=60)
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


@frappe.whitelist()
def get_loan_estimate(loan_product, loan_amount, repayment_periods):
    """Estimate monthly payment, total payable, and total interest for a loan.

    Uses simple amortization: monthly_payment = P * r / (1 - (1+r)^-n)
    where P = principal, r = monthly rate, n = periods.
    """
    customer = _require_customer()
    loan_amount = flt(loan_amount)
    repayment_periods = int(repayment_periods)

    if loan_amount <= 0:
        frappe.throw("Loan amount must be positive.")
    if repayment_periods <= 0:
        frappe.throw("Repayment periods must be positive.")

    rate = flt(frappe.db.get_value("Loan Product", loan_product, "rate_of_interest") or 0)
    max_amount = flt(frappe.db.get_value("Loan Product", loan_product, "maximum_loan_amount") or 0)
    if max_amount and loan_amount > max_amount:
        frappe.throw(f"Amount exceeds the maximum for this product ({max_amount}).")

    monthly_rate = rate / 100 / 12
    if monthly_rate > 0:
        monthly_payment = loan_amount * monthly_rate / (1 - (1 + monthly_rate) ** (-repayment_periods))
    else:
        monthly_payment = loan_amount / repayment_periods

    total_payable = monthly_payment * repayment_periods
    total_interest = total_payable - loan_amount

    return {
        "monthly_payment": flt(monthly_payment),
        "total_payable": flt(total_payable),
        "total_interest": flt(total_interest),
        "rate_of_interest": rate,
        "loan_amount": loan_amount,
        "repayment_periods": repayment_periods,
    }


@frappe.whitelist()
def get_my_applications():
    """List the borrower's submitted loan applications with status."""
    customer = _require_customer()
    applications = frappe.get_all(
        "Loan Application",
        filters={"applicant_type": "Customer", "applicant": customer},
        fields=[
            "name",
            "loan_amount",
            "status",
            "loan_product",
            "repayment_periods",
            "creation",
            "modified",
        ],
        order_by="modified desc",
    )
    for app in applications:
        app["product_name"] = frappe.db.get_value(
            "Loan Product", app.loan_product, "product_name"
        ) or app.loan_product
    return {"applications": applications}


@frappe.whitelist()
def get_portal_notifications():
    """Recent notification log entries for the borrower's loans."""
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)
    # Portal staff (collectors/officers) don't have a Customer linked — return
    # empty notifications for them so the notification bell doesn't 403.
    from lms_saas.install import PORTAL_STAFF_ROLE

    roles = set(frappe.get_roles(frappe.session.user))
    if PORTAL_STAFF_ROLE in roles and "Customer" not in roles:
        return {"notifications": [], "unread_count": 0}
    customer = _require_customer()
    loan_names = frappe.get_all(
        "Loan",
        filters={"applicant_type": "Customer", "applicant": customer, "docstatus": 1},
        pluck="name",
    )
    if not loan_names:
        return {"notifications": [], "unread_count": 0}

    notifications = frappe.get_all(
        "LMS Notification Log",
        filters={"loan": ("in", loan_names), "status": "Sent"},
        fields=[
            "name",
            "loan",
            "reminder_type",
            "notification_date",
            "channel",
            "status",
            "recipient",
            "message_preview",
            "read_on",
        ],
        order_by="notification_date desc",
        limit_page_length=20,
    )
    # Unread = delivered (Sent) and not yet opened (read_on is null).
    unread_count = frappe.db.count(
        "LMS Notification Log",
        {"loan": ("in", loan_names), "status": "Sent", "read_on": ("is", "not set")},
    )
    return {"notifications": notifications, "unread_count": unread_count}


@frappe.whitelist()
def mark_notifications_read():
    """Mark all the borrower's unread notifications as read (bell open = seen)."""
    customer = _require_customer()
    loan_names = frappe.get_all(
        "Loan",
        filters={"applicant_type": "Customer", "applicant": customer, "docstatus": 1},
        pluck="name",
    )
    if not loan_names:
        return {"marked": 0}

    now = frappe.utils.now_datetime()
    updated = frappe.db.set_value(
        "LMS Notification Log",
        {"loan": ("in", loan_names), "status": "Sent", "read_on": ("is", "not set")},
        "read_on",
        now,
    )
    frappe.db.commit()
    return {"marked": updated}


@frappe.whitelist()
def get_account_overview():
    """KYC/AML status, notification preferences, and document list for the borrower."""
    customer = _require_customer()
    compliance = frappe.db.get_value(
        "LMS Borrower Compliance",
        {"customer": customer},
        [
            "name",
            "kyc_status",
            "aml_status",
            "consent_given",
            "consent_date",
            "id_document_proof",
            "proof_of_address",
            "credit_score",
            "debt_to_income_ratio",
        ],
        as_dict=True,
    )
    customer_doc = frappe.db.get_value(
        "Customer", customer, ["name", "customer_name", "email_id", "mobile_no"], as_dict=True
    )
    return {
        "compliance": compliance,
        "customer": customer_doc,
    }
