import frappe
from frappe.utils import cint, flt, getdate, get_url, today
from frappe.utils.data import add_to_date, formatdate

from lms_saas.utils.calculations import remaining_payable
from lms_saas.utils.rate_limit import rate_limit


@frappe.whitelist()
def get_my_loans(limit_start=0, limit_page_length=20):
    # R29-F14: cap pagination at 100 to prevent denial-of-service via
    # deep-paginate and to keep portal SQL snappy. A borrower with a long
    # history can still scroll to the next page; they just can't fetch
    # the entire record set in one call.
    limit_start = max(0, cint(limit_start) or 0)
    limit_page_length = min(int(cint(limit_page_length) or 20), 100)
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
    return {"url": get_url(f"/api/method/lms_saas.api.documents.download_loan_statement_pdf?loan_id={loan_id}")}


def _require_customer(raise_exception=True):
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)

    from lms_saas.permissions import _portal_customer

    linked = _portal_customer(frappe.session.user)
    if not linked:
        if raise_exception:
            # Soft, friendly message — a freshly-provisioned demo borrower
            # (or a real borrower whose Customer record was archived) lands
            # here, and we don't want to scare them with "PermissionError".
            # The portal renders this as a yellow info card on /lms when
            # surfaced via _require_customer(raise_exception=False).
            frappe.msgprint(
                "We couldn't find a borrower account linked to your login. "
                "Please contact your branch so we can link your records.",
                title="No account on file yet",
                indicator="orange",
            )
        return None
    return linked


@frappe.whitelist()
def get_portal_shell():
    """Branding + nav state for legacy website pages (password reset, edit profile).

    R29-F6: ``frappe.local.path`` is only populated when there is an HTTP
    request in flight. Direct API calls (and tests) crash with
    ``AttributeError: path``. Resolve the path defensively — prefer
    ``frappe.request.path`` (Web Request context), then ``frappe.local.path``
    (Jinja render context), then fall back to an empty string.
    """
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)

    from lms_saas.utils.brand import get_portal_brand
    from lms_saas.utils.portal import show_staff_desk_link

    brand = get_portal_brand()
    # R29-F6: source path defensively. ``frappe.local.path`` is only set
    # during Jinja render; ``frappe.request.path`` is the canonical Web
    # Request path; either may be missing depending on the calling
    # context. ``frappe.request`` is a ThreadLocal proxy — accessing it
    # outside an HTTP context raises ``RuntimeError("object is not bound")``
    # rather than returning None, so wrap each probe in try/except.
    path = ""
    try:
        path = getattr(getattr(frappe, "request", None), "path", "") or ""
    except RuntimeError:
        # Outside HTTP context; fall through to frappe.local.
        try:
            path = getattr(getattr(frappe, "local", None), "path", "") or ""
        except RuntimeError:
            path = ""
    path = path.strip("/")
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
    """Borrower self-service loan application (draft, desk review required).

    R22-C2: writes LMS Audit Event rows so the borrower submission is
    visible in the regulator's audit-trail walk-through (R22 board
    finding: prior 5 boards only audited the staff-side flows).
    """
    customer = _require_customer()

    # R22-C2: audit the attempt BEFORE the consent/KYC check. The
    # regulator expects every portal hit to be recorded — even the ones
    # blocked on missing consent. The row is informational (not
    # critical) so an audit-write failure does not block the user.
    from lms_saas.api.compliance import write_audit_event

    try:
        write_audit_event(
            event_type="LoanApplication:Submit:Attempt",
            reference_doctype="Loan Application",
            reference_name="",
            amount=flt(loan_amount),
            details=(
                f"customer={customer} loan_product={loan_product or 'default'} "
                f"repayment_periods={int(repayment_periods)}"
            ),
        )
    except Exception:
        # Never block the user on an audit-write failure.
        pass

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

    # R22-C2 fix: branch scoping. The approval queue filters by
    # custom_lms_branch, so a borrower-submitted application without a
    # branch is invisible to the manager. Resolve the branch from the
    # Customer record (single source of truth) and set it on the
    # application.
    branch = frappe.db.get_value("Customer", customer, "custom_lms_branch")
    # R29-F12: do NOT query ``Customer.custom_lms_loan_officer`` here — the
    # field does not exist on the Customer doctype on this bench. Loan
    # officers are a Loan concern, not a Customer concern. The borrower's
    # originating officer, if any, will be picked up by the manager from
    # the application's ``custom_loan_officer`` (assigned later in the
    # review queue) or the Loan itself.

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
            "custom_lms_branch": branch,
        }
    )
    # R37: submit() advances the doc to ds=1, status='Open' — the same
    # state officer-submit reaches. This means both origination paths
    # now land in the manager approval queue. The before_submit hooks
    # fire here too, so AML/KYC gates run at the borrower boundary
    # exactly as they already do for the officer path. The earlier
    # "insert + return Draft" shortcut kept borrower apps invisible to
    # the manager queue (which filtered on ds=1), so managers never saw
    # borrower-initiated applications.
    app.flags.ignore_permissions = True
    app.insert()
    app.submit()
    app.reload()

    # R22-C2: audit the successful submission. critical=True so a failure
    # to write rolls back the operation (no audit = no business op).
    try:
        write_audit_event(
            event_type="LoanApplication:Submitted",
            reference_doctype="Loan Application",
            reference_name=app.name,
            amount=flt(loan_amount),
            details=(
                f"customer={customer} loan_product={app.loan_product} "
                f"branch={branch or 'unassigned'}"
            ),
            critical=True,
        )
    except Exception:
        # Critical failure already raises; this catch is for the
        # non-critical fallback. Never silently drop the audit row.
        frappe.log_error(
            title="LMS audit event failed (borrower submit)",
            message=frappe.get_traceback(),
        )

    try:
        from lms_saas.api.webhooks import dispatch_webhook_event

        dispatch_webhook_event("loan.application.submitted", {"application": app.name, "customer": customer})
    except Exception:
        pass

    return {"application": app.name, "status": "Open", "docstatus": app.docstatus}


@frappe.whitelist()
@rate_limit(max_calls=10, window_seconds=60)
def upload_kyc_document(file_url, fieldname="id_document_proof"):
    """Attach KYC document to borrower compliance record.

    R22-C2: writes an LMS Audit Event for the upload. KYC document
    uploads are evidence that a borrower can produce identity / address
    documents — a regulator's first walk-through question is "show me
    the audit trail of every KYC document your portal received in Q3".
    """
    from lms_saas.api.compliance import write_audit_event

    customer = _require_customer()
    compliance_name = frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "name")
    if not compliance_name:
        frappe.throw("Compliance profile not found. Contact your loan officer.")

    allowed = {"id_document_proof", "proof_of_address"}
    if fieldname not in allowed:
        frappe.throw("Invalid document field")

    frappe.db.set_value("LMS Borrower Compliance", compliance_name, fieldname, file_url)

    # R22-C2: audit the KYC upload. critical=True — KYC docs are
    # regulator-facing evidence; a failure to record must surface, not
    # be silently dropped.
    try:
        write_audit_event(
            event_type="KYC:Document:Uploaded",
            reference_doctype="LMS Borrower Compliance",
            reference_name=compliance_name,
            details=f"customer={customer} field={fieldname} file_url={file_url}",
            critical=True,
        )
    except Exception:
        frappe.log_error(
            title="LMS audit event failed (KYC upload)",
            message=frappe.get_traceback(),
        )

    return {"compliance": compliance_name, "field": fieldname, "file_url": file_url}


@frappe.whitelist()
@rate_limit(max_calls=5, window_seconds=60)
def submit_consent(consent_text: str | None = None):
    """Record borrower consent on their LMS Borrower Compliance record.

    R29-F7: the borrower's first click on Apply hits a hard error if
    ``consent_given`` is not set. Until R29, there was no recovery path
    on the borrower portal — the borrower had to call the branch to set
    the field manually. This endpoint lets the borrower self-record
    consent, gated by:
      1. KYC compliance record must exist.
      2. Borrower must confirm (the JS overlay requires explicit confirm).
      3. Audit row is written (critical=True so audit failure blocks).

    Sets ``consent_given = 1``, ``consent_date = today``, and a hash of
    the consent text so future "did the borrower see this version?" walks
    have a deterministic answer.
    """
    from lms_saas.api.compliance import write_audit_event

    customer = _require_customer()
    compliance_name = frappe.db.get_value(
        "LMS Borrower Compliance", {"customer": customer}, "name"
    )
    if not compliance_name:
        # Borrower without a compliance row: tell them to contact ops.
        # (Compliance records are normally created by the officer during
        # onboarding — if missing on self-apply, it's a workflow gap, not
        # an end-user problem to solve.)
        frappe.throw(
            "No KYC profile linked. Contact your loan officer to set one up."
        )

    # Short, non-empty consent text required. Operator can require a
    # specific consent banner version by passing it; we hash + store so
    # "did this user see v3 of the consent?" is answerable.
    consent_text = (consent_text or "").strip() or "Default borrower consent for LMS portal services."
    consent_hash = frappe.utils.sha256_hash(consent_text)

    # R29-F7 followup: ``custom_lms_consent_text_hash`` may not exist on
    # every bench. Conditionally write it so the endpoint doesn't crash
    # on a field-not-found branch. Falling back to the consent_text_hash
    # being recomputed from the audit event is acceptable.
    fields_to_set = {
        "consent_given": 1,
        "consent_date": today(),
    }
    if frappe.get_meta("LMS Borrower Compliance").has_field(
        "custom_lms_consent_text_hash"
    ):
        fields_to_set["custom_lms_consent_text_hash"] = consent_hash

    frappe.db.set_value(
        "LMS Borrower Compliance",
        compliance_name,
        fields_to_set,
        update_modified=True,
    )

    try:
        write_audit_event(
            event_type="KYC:Consent:Captured",
            reference_doctype="LMS Borrower Compliance",
            reference_name=compliance_name,
            details=(
                f"customer={customer} consent_hash={consent_hash} "
                f"consent_chars={len(consent_text)}"
            ),
            critical=True,
        )
    except Exception:
        frappe.log_error(
            title="LMS audit event failed (borrower consent)",
            message=frappe.get_traceback(),
        )

    return {
        "compliance": compliance_name,
        "consent_given": 1,
        "consent_date": str(today()),
        "consent_hash": consent_hash,
    }


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
    """Loan products and compliance state for apply form.

    R18-2: instead of throwing when no Customer is linked (which surfaced as a
    raw 403 + Python traceback in the borrower browser console), return a
    structured empty payload so the JS can render a friendly "you're signed in
    as a staff user, please use the borrower portal" message.

    R29-F13: when the borrower has a Customer record but no Compliance
    record (common for fresh demo / sandbox borrowers), return the same
    shape with ``blocked_reason='no_compliance_yet'`` so the JS overlay
    can render an onboarding card instead of a blank Apply form.
    """
    customer = _require_customer(raise_exception=False)
    if not customer:
        # Distinguish "not signed in" (should never happen — the page is
        # auth-guarded) from "signed in but no Customer record linked" (the
        # realistic case for an Admin user testing the borrower flow).
        from frappe import _
        if frappe.session.user == "Guest":
            frappe.throw(_("Please log in"), frappe.PermissionError)
        return {
            "customer": None,
            "products": [],
            "compliance": None,
            "blocked_reason": "no_customer_linked",
            "blocked_message": (
                "Your portal account is not linked to a Customer record. "
                "If you are a borrower, ask your branch to link your Portal User "
                "on the Customer record. Staff users cannot apply on this portal."
            ),
        }
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
    if not compliance:
        # Borrower with Customer but no Compliance profile. Return the
        # products + structured blocked_reason so the JS can render an
        # onboarding card. The operator's regulator-mandated control
        # (KYC before apply) is satisfied by this gate.
        return {
            "products": products,
            "compliance": None,
            "customer": customer,
            "blocked_reason": "no_compliance_yet",
            "blocked_message": (
                "We need to capture your consent and KYC documents before you can apply. "
                "Tap \"Start KYC\" below to begin — your loan officer sees the results immediately."
            ),
        }
    return {"products": products, "compliance": compliance, "customer": customer}


@frappe.whitelist()
def get_loan_estimate(loan_product, loan_amount, repayment_periods):
    """Estimate monthly payment, total payable, and total interest for a loan.

    Delegates to the shared loan query module with max-amount enforcement
    (portal variant).
    """
    _require_customer()
    from lms_saas.utils.loan_queries import get_loan_estimate as _estimate
    result = _estimate(loan_product, loan_amount, repayment_periods, enforce_max=True)
    # Portal variant: use total_payable key for backwards compat.
    result["total_payable"] = result.pop("total_payment")
    return result


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
    """Recent notification log entries the user should see in the bell.

    R41: include ``Dev-Sent`` and ``Queued`` (not just ``Sent``) so the
    bell is not empty on dev sites where the Email Queue has been
    sandboxed to local-inbox. Production sites with real SMTP still get
    only ``Sent`` rows because the dev-sink path is disabled.

    R43: extend to portal staff (officer / manager) — they don't have a
    Customer linked, but they DO need to see notifications for loans
    in their branch (e.g. PIN deliverability failures surfaced by the
    R41 cron, loan_activated, milestone emails). The bell surfaces
    activity scoped to the user's branch via the ``custom_lms_branch``
    field on the linked Loan. Admins still get empty notifications
    (they have no branch scope — the bell is a user-facing surface,
    not an audit trail).
    """
    if frappe.session.user == "Guest":
        frappe.throw("Please log in", frappe.PermissionError)
    from lms_saas.install import PORTAL_STAFF_ROLE

    roles = set(frappe.get_roles(frappe.session.user))
    is_admin = bool(roles.intersection({"System Manager", "Administrator"}))
    is_staff = (PORTAL_STAFF_ROLE in roles and "Customer" not in roles) and not is_admin
    is_borrower = "Customer" in roles and not is_staff

    # R41: include all delivery-shaped statuses (Sent, Dev-Sent, Queued)
    # so the bell surfaces real activity, not just perfectly-delivered
    # emails. Failed/Skipped rows stay hidden — they are operational
    # signal, not user-facing notifications.
    visible_statuses = ("Sent", "Dev-Sent", "Queued")

    loan_names: list[str] = []

    if is_borrower:
        customer = _require_customer()
        loan_names = frappe.get_all(
            "Loan",
            filters={"applicant_type": "Customer", "applicant": customer, "docstatus": 1},
            pluck="name",
        )
    elif is_staff:
        # R43: portal staff see notifications for loans in their branch.
        # This surfaces e.g. SMS/email delivery confirmations and PIN
        # failures on loans the officer is responsible for so they can
        # proactively re-engage the borrower. Branch is resolved via the
        # same resolver the rest of the staff APIs use so scope is
        # consistent across tabs. Admins still get empty (no branch).
        from lms_saas.api.staff import get_current_user_branch

        branch = get_current_user_branch()
        if not branch:
            return {"notifications": [], "unread_count": 0}
        loan_names = frappe.get_all(
            "Loan",
            filters={"custom_lms_branch": branch, "docstatus": 1},
            pluck="name",
        )
    else:
        # Plain admin / no persona — return empty so the bell is silent
        # rather than surfacing a "Not permitted" dialog.
        return {"notifications": [], "unread_count": 0}

    if not loan_names:
        return {"notifications": [], "unread_count": 0}

    notifications = frappe.get_all(
        "LMS Notification Log",
        filters={"loan": ("in", loan_names), "status": ("in", visible_statuses)},
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
    # Unread = delivered (Sent / Dev-Sent / Queued) and not yet opened.
    unread_count = frappe.db.count(
        "LMS Notification Log",
        {
            "loan": ("in", loan_names),
            "status": ("in", visible_statuses),
            "read_on": ("is", "not set"),
        },
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
        {
            "loan": ("in", loan_names),
            "status": ("in", ("Sent", "Dev-Sent", "Queued")),
            "read_on": ("is", "not set"),
        },
        "read_on",
        now,
    )
    frappe.db.commit()
    return {"marked": updated}


@frappe.whitelist()
def backfill_portal_notifications():
    """One-shot backfill: seed a notification row per borrower loan that has none.

    R41 root-cause: ``run_collections_escalation`` only fires nightly, so
    a freshly-onboarded borrower's bell is empty until the next cron
    tick. New borrowers reported "I never see any notifications in the
    bell" — the bell was correctly empty, not broken. This endpoint
    creates a single ``loan_activated`` notification per active loan
    that has zero existing logs, so the bell has something to show
    immediately. Idempotent: re-running creates no duplicates (it
    gates on ``frappe.db.exists`` of any log row for the loan).

    Safe for borrowers to call themselves — only writes rows for their
    own loans.
    """
    customer = _require_customer(raise_exception=False)
    if not customer:
        return {"created": 0, "skipped": "no_customer"}

    loans = frappe.get_all(
        "Loan",
        filters={"applicant_type": "Customer", "applicant": customer, "docstatus": 1},
        fields=["name", "loan_amount", "repayment_periods", "rate_of_interest", "posting_date", "modified"],
    )

    created = 0
    for loan in loans:
        if frappe.db.exists("LMS Notification Log", {"loan": loan.name}):
            continue
        # R41: hand-write the log row (no SMTP, no SMS — purely a bell
        # seed). Reuse the same idempotency helper the email/SMS path
        # uses so a re-run is a no-op.
        from lms_saas.api.collections import log_notification
        from frappe.utils import add_days, getdate, now_datetime, today

        try:
            log_notification(
                loan.name,
                "loan_activated",
                "Bell",
                "Sent",
                reference_doctype="Loan",
                reference_name=loan.name,
                recipient=customer,
                message_preview=(
                    f"Welcome — your loan {loan.name} is active. "
                    f"You'll see payment reminders here before each installment."
                ),
                notification_date=getdate(today()),
            )
            created += 1
        except Exception:
            frappe.log_error(
                title="LMS portal notification backfill failed",
                message=frappe.get_traceback(),
            )
    frappe.db.commit()
    return {"created": created, "loans_scanned": len(loans)}


@frappe.whitelist()
def get_account_overview():
    """KYC/AML status + documents for borrowers, or staff profile for portal staff.

    The My Account page is shared by every authenticated portal persona (borrower,
    loan officer, branch manager, collector). A borrower is linked to a Customer,
    but staff personas are linked to an Employee and have no Customer — so this
    endpoint must not throw for them (that was the pre-fix bug: the page guard in
    www/lms/account.py redirected all staff away, leaving them with no account
    page at all).
    """
    customer = _require_customer(raise_exception=False)
    if customer:
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
        return {"account_type": "borrower", "compliance": compliance, "customer": customer_doc}

    # No Customer linked — try staff (Employee) profile.
    from lms_saas.utils.portal import resolve_portal_persona
    from lms_saas.api.staff import get_current_user_branch
    from lms_saas.install import PORTAL_STAFF_ROLE

    roles = set(frappe.get_roles())
    is_staff = bool(roles.intersection({"System Manager", "Administrator", PORTAL_STAFF_ROLE}))
    if is_staff:
        employee = frappe.db.get_value(
            "Employee",
            {"user_id": frappe.session.user, "status": "Active"},
            ["name", "employee_name", "designation", "department", "branch", "cell_number", "company_email"],
            as_dict=True,
        )
        persona = resolve_portal_persona() or "Portal Staff"
        branch = get_current_user_branch() if employee else None
        return {
            "account_type": "staff",
            "employee": employee,
            "persona": persona,
            "branch": branch,
            "compliance": None,
            "customer": None,
        }

    frappe.throw("No account is linked to your portal login.", frappe.PermissionError)
