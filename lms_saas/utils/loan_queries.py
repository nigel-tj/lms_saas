"""Borrower/loan query module — single source of truth for borrower and loan detail queries.

Consolidates the near-identical ``get_borrower_detail``, ``get_loan_detail``,
``search_borrowers``, and ``record_repayment`` implementations that were
duplicated across ``api/officer.py``, ``api/manager.py``, and ``api/portal.py``.

Interface (small, deep):

- :func:`get_borrower` — full borrower profile (contact, KYC, loans, collateral, repayments).
- :func:`get_loan` — full loan detail (schedule, repayments, disbursements, collateral).
- :func:`search_borrowers` — paginated borrower search with optional branch/status filters.
- :func:`record_repayment` — create + submit a Loan Repayment with audit event.

Each role endpoint (officer, manager, portal) becomes a thin wrapper:
guard + delegate to this module.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt, today, getdate, cint


# ---------------------------------------------------------------------------
# Borrower queries
# ---------------------------------------------------------------------------

def get_borrower(
	customer_name: str,
	*,
	include_household: bool = False,
	include_loans: bool = True,
	include_compliance: bool = True,
	include_collateral: bool = True,
	include_repayments: bool = True,
) -> dict:
	"""Full borrower profile: contact info, KYC, loans, collateral, repayments.

	Args:
		customer_name: the Customer name.
		include_household: include marital status / spouse / physical address
			(used by the officer Loan Application form to pre-fill fields).
		include_loans: include the borrower's submitted loans.
		include_compliance: include the LMS Borrower Compliance record.
		include_collateral: include collateral links across all loans.
		include_repayments: include the 20 most recent repayments.

	Returns:
		dict with the borrower record and requested includes.

	Raises:
		frappe.DoesNotExistError: if the Customer doesn't exist.
	"""
	if not frappe.db.exists("Customer", customer_name):
		frappe.throw(_("Customer {0} not found.").format(customer_name))

	cust = frappe.get_doc("Customer", customer_name)
	customer: dict = {
		"name": cust.name,
		"customer_name": cust.customer_name,
		"email_id": cust.email_id or "",
		"mobile_no": cust.mobile_no or "",
		"custom_lms_branch": cust.get("custom_lms_branch", ""),
		"custom_national_id_number": cust.get("custom_national_id_number", ""),
		"customer_group": cust.customer_group or "",
		"territory": cust.territory or "",
		"disabled": cust.disabled,
	}

	if include_household:
		customer.update({
			"marital_status": cust.get("lms_marital_status") or "",
			"spouse_name": cust.get("lms_spouse_name") or "",
			"spouse_dob": cust.get("lms_spouse_dob") or "",
			"spouse_contact": cust.get("lms_spouse_contact") or "",
			"physical_address": cust.get("lms_physical_address") or "",
		})

	loans = []
	if include_loans:
		loans = frappe.get_all(
			"Loan",
			filters={"applicant": customer_name, "docstatus": 1},
			fields=[
				"name", "loan_amount", "total_payment", "total_amount_paid",
				"status", "rate_of_interest", "repayment_periods",
				"custom_days_past_due", "disbursed_amount",
			],
			order_by="creation desc",
			limit_page_length=0,
		)
		for loan in loans:
			loan["outstanding"] = flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0)
			loan["dpd"] = loan.custom_days_past_due or 0
		customer["loans"] = loans

	if include_compliance:
		compliance = frappe.db.get_value(
			"LMS Borrower Compliance",
			{"customer": customer_name},
			["name", "kyc_status", "consent_given", "consent_date", "aml_status", "credit_score"],
			as_dict=True,
		)
		customer["compliance"] = compliance or {}

	if include_collateral and loans:
		collateral_links = frappe.get_all(
			"LMS Loan Collateral",
			filters={"parenttype": "Loan", "parent": ("in", [l["name"] for l in loans])},
			fields=["collateral", "collateral_type", "allocated_value", "parent"],
			limit_page_length=0,
		)
		customer["collateral"] = collateral_links
	elif include_collateral:
		customer["collateral"] = []

	if include_repayments:
		repayments = frappe.get_all(
			"Loan Repayment",
			filters={"applicant": customer_name, "docstatus": 1},
			fields=["name", "against_loan", "amount_paid", "posting_date"],
			order_by="posting_date desc",
			limit_page_length=20,
		)
		customer["recent_repayments"] = repayments

	return {"borrower": customer}


def search_borrowers(
	query: str = "",
	*,
	status: str | None = None,
	branch: str | None = None,
	limit: int = 50,
) -> dict:
	"""Search borrowers by name, email, mobile, or national ID.

	Args:
		query: free-text search string (matches customer_name, email_id,
			mobile_no, custom_national_id_number).
		status: optional filter — ``"active"`` (not disabled) or ``"disabled"``.
		branch: optional branch (Cost Center) filter.
		limit: max results.

	Returns:
		``{"borrowers": [...]}`` with loan_count, active_loans, kyc_status
		enriched on each row.
	"""
	filters: dict = {}
	if status == "active":
		filters["disabled"] = 0
	elif status == "disabled":
		filters["disabled"] = 1
	if branch:
		filters["custom_lms_branch"] = branch

	if query:
		filters["customer_name"] = ("like", f"%{query}%")

	customers = frappe.get_all(
		"Customer",
		filters=filters,
		fields=[
			"name", "customer_name", "email_id", "mobile_no",
			"custom_lms_branch", "custom_national_id_number",
		],
		order_by="customer_name asc",
		limit_page_length=limit,
	)

	# If the query didn't match on name, also try email/mobile/national_id.
	if query and not customers:
		or_filters = [
			{"email_id": ("like", f"%{query}%")},
			{"mobile_no": ("like", f"%{query}%")},
			{"custom_national_id_number": ("like", f"%{query}%")},
		]
		customers = frappe.get_all(
			"Customer",
			filters=filters,
			or_filters=or_filters,
			fields=[
				"name", "customer_name", "email_id", "mobile_no",
				"custom_lms_branch", "custom_national_id_number",
			],
			order_by="customer_name asc",
			limit_page_length=limit,
		)

	for c in customers:
		c["loan_count"] = frappe.db.count("Loan", {"applicant": c.name, "docstatus": 1})
		c["active_loans"] = frappe.db.count(
			"Loan",
			{"applicant": c.name, "docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
		)
		c["kyc_status"] = frappe.db.get_value(
			"LMS Borrower Compliance", {"customer": c.name}, "kyc_status"
		) or "Pending"

	return {"borrowers": customers}


# ---------------------------------------------------------------------------
# Loan queries
# ---------------------------------------------------------------------------

def get_loan(loan_name: str, *, include_paid_flag: bool = True) -> dict:
	"""Full loan detail: schedule, repayments, disbursements, collateral, borrower.

	Args:
		loan_name: the Loan name.
		include_paid_flag: if True, cross-check schedule rows against
			posted repayments to mark each installment ``paid`` /
			``demand_generated`` (officer/manager variant).  If False,
			use the schedule's own ``demand_generated`` column (manager
			variant).

	Returns:
		dict with ``loan``, ``schedule``, ``repayments``, ``disbursements``,
		``collateral``.

	Raises:
		frappe.DoesNotExistError: if the Loan doesn't exist.
	"""
	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)

	# Schedule — resolve the Loan Repayment Schedule doc(s) for this loan,
	# then aggregate their child Repayment Schedule rows.
	schedule = []
	for lnrs in frappe.get_all(
		"Loan Repayment Schedule", filters={"loan": loan_name}, pluck="name"
	):
		fields = [
			"payment_date", "principal_amount", "interest_amount",
			"total_payment", "balance_loan_amount",
		]
		if not include_paid_flag:
			# Manager variant reads demand_generated from the row directly.
			fields.append("demand_generated")
		for row in frappe.get_all(
			"Repayment Schedule",
			filters={"parent": lnrs, "parenttype": "Loan Repayment Schedule"},
			fields=fields,
			order_by="payment_date asc",
			limit_page_length=0,
		):
			schedule.append(row)
	schedule.sort(key=lambda r: (getdate(r.get("payment_date")) or getdate("1900-01-01")))

	# Repayments
	repayments = frappe.get_all(
		"Loan Repayment",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "amount_paid", "posting_date", "docstatus"],
		order_by="posting_date desc",
		limit_page_length=50,
	)
	for r in repayments:
		r["status"] = "Submitted" if cint(r.get("docstatus")) == 1 else "Draft"

	# Cross-check against posted Loan Repayments to mark each installment
	# paid / demand_generated (officer variant).
	if include_paid_flag and schedule:
		paid_amount_by_date: dict = {}
		for r in repayments:
			posting = r.get("posting_date")
			amt = flt(r.get("amount_paid") or 0)
			if posting:
				paid_amount_by_date[posting] = paid_amount_by_date.get(posting, 0) + amt
		for row in schedule:
			posting = row.get("payment_date")
			row["paid"] = flt(paid_amount_by_date.get(posting, 0)) >= flt(row.get("total_payment") or 0)
			row["demand_generated"] = bool(posting) and getdate(posting) < getdate(today()) and not row["paid"]
	elif not include_paid_flag:
		# Manager variant: map demand_generated to a 'paid' flag.
		for row in schedule:
			row["paid"] = cint(row.get("demand_generated"))

	# Disbursements
	disbursements = frappe.get_all(
		"Loan Disbursement",
		filters={"against_loan": loan_name, "docstatus": 1},
		fields=["name", "disbursed_amount", "posting_date", "status"],
		order_by="posting_date desc",
		limit_page_length=20,
	)

	borrower_name = frappe.db.get_value("Customer", loan.applicant, "customer_name") if loan.applicant else ""

	# Collateral
	collateral = frappe.get_all(
		"LMS Loan Collateral",
		filters={"parent": loan_name, "parenttype": "Loan"},
		fields=["collateral", "collateral_type", "allocated_value"],
		limit_page_length=0,
	)

	return {
		"loan": {
			"name": loan.name,
			"applicant": loan.applicant,
			"applicant_type": loan.applicant_type,
			"borrower_name": borrower_name,
			"loan_amount": loan.loan_amount,
			"rate_of_interest": loan.rate_of_interest,
			"repayment_periods": loan.repayment_periods,
			"repayment_method": loan.repayment_method,
			"total_payment": loan.total_payment,
			"total_amount_paid": loan.total_amount_paid,
			"disbursed_amount": loan.disbursed_amount,
			"status": loan.status,
			"docstatus": loan.docstatus,
			"custom_lms_branch": loan.get("custom_lms_branch", ""),
			"custom_loan_officer": loan.get("custom_loan_officer", ""),
			"custom_days_past_due": loan.get("custom_days_past_due", 0),
			"outstanding": flt(loan.total_payment or 0) - flt(loan.total_amount_paid or 0),
			"dpd": loan.get("custom_days_past_due", 0),
		},
		"schedule": schedule,
		"repayments": repayments,
		"disbursements": disbursements,
		"collateral": collateral,
	}


# ---------------------------------------------------------------------------
# Repayment creation
# ---------------------------------------------------------------------------

def record_repayment(
	loan_name: str,
	amount: float,
	*,
	payment_mode: str = "Cash",
	posting_date: str | None = None,
	audit_event_type: str = "Repayment:OfficerRecorded",
	admin_override: bool = False,
) -> dict:
	"""Create + submit a Loan Repayment and emit an audit event.

	Args:
		loan_name: the Loan name.
		amount: repayment amount (must be positive).
		payment_mode: payment mode label (for the audit trail).
		posting_date: posting date (defaults to today).
		audit_event_type: the LMS Audit Event type label
			(e.g. ``"Repayment:OfficerRecorded"``,
			``"Repayment:ManagerRecorded"``).
		admin_override: whether the caller is an admin (for the audit trail).

	Returns:
		``{"status": "recorded", "loan": ..., "repayment": ..., "amount": ...}``

	Raises:
		frappe.ValidationError: if the amount is non-positive or the loan
			is Closed / Written Off / Cancelled.
		frappe.DoesNotExistError: if the Loan doesn't exist.
	"""
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Repayment amount must be positive."))

	if not frappe.db.exists("Loan", loan_name):
		frappe.throw(_("Loan {0} not found.").format(loan_name))

	loan = frappe.get_doc("Loan", loan_name)

	# Edge: closed / written-off / cancelled loans cannot accept new repayments.
	if loan.status in ("Closed", "Written Off", "Cancelled"):
		frappe.throw(
			_("Cannot record repayment on a {0} loan.").format(loan.status),
			frappe.ValidationError,
		)

	repayment = frappe.get_doc(
		{
			"doctype": "Loan Repayment",
			"against_loan": loan_name,
			"applicant_type": loan.applicant_type,
			"applicant": loan.applicant,
			"company": loan.company,
			"posting_date": posting_date or today(),
			"amount_paid": amount,
		}
	)
	repayment.flags.ignore_permissions = True
	repayment.insert()
	repayment.submit()

	# Emit an LMS Audit Event so the regulator can distinguish
	# officer-recorded from manager-recorded from admin-recorded.
	try:
		from lms_saas.api.compliance import write_audit_event

		write_audit_event(
			event_type=audit_event_type,
			reference_doctype="Loan Repayment",
			reference_name=repayment.name,
			amount=amount,
			company=loan.company,
			details=(
				f"loan={loan_name}; admin_override={admin_override}; "
				f"loan_status={loan.status}; branch={loan.get('custom_lms_branch') or 'unassigned'}; "
				f"payment_mode={payment_mode}"
			),
			critical=True,
		)
	except Exception:
		frappe.log_error(title=f"{audit_event_type} audit failed", message=frappe.get_traceback())

	return {
		"status": "recorded",
		"loan": loan_name,
		"repayment": repayment.name,
		"amount": amount,
	}


# ---------------------------------------------------------------------------
# Loan estimate
# ---------------------------------------------------------------------------

def get_loan_estimate(
	loan_product: str,
	loan_amount: float,
	repayment_periods: int = 6,
	*,
	enforce_max: bool = False,
) -> dict:
	"""Return a loan estimate (monthly payment, total interest, total payment).

	Uses the Loan Product's rate of interest if available, falling back to
	a flat 24% annual rate.

	Args:
		loan_product: the Loan Product name.
		loan_amount: principal amount.
		repayment_periods: number of repayment periods (months).
		enforce_max: if True, throw when the amount exceeds the product's
			``maximum_loan_amount`` (portal variant).

	Returns:
		dict with ``monthly_payment``, ``total_payment``, ``total_interest``,
		``rate``, ``periods``.
	"""
	amount = flt(loan_amount)
	periods = cint(repayment_periods)
	if amount <= 0 or periods <= 0:
		frappe.throw(_("Loan amount and repayment periods must be positive."))

	if not frappe.db.exists("Loan Product", loan_product):
		frappe.throw(_("Loan product {0} not found.").format(loan_product))

	product = frappe.db.get_value(
		"Loan Product", loan_product,
		["rate_of_interest", "maximum_loan_amount"],
		as_dict=True,
	)

	if enforce_max:
		max_amount = flt(product.maximum_loan_amount or 0)
		if max_amount and amount > max_amount:
			frappe.throw(
				_("Amount exceeds the maximum for this product ({0}).").format(max_amount),
			)

	rate = flt(product.rate_of_interest or 0)
	if rate <= 0:
		rate = 24.0  # fallback

	monthly_rate = rate / 100 / 12
	if monthly_rate > 0:
		monthly_payment = amount * monthly_rate / (1 - (1 + monthly_rate) ** (-periods))
	else:
		monthly_payment = amount / periods

	total_payment = monthly_payment * periods
	total_interest = total_payment - amount

	return {
		"monthly_payment": flt(monthly_payment, 2),
		"total_payment": flt(total_payment, 2),
		"total_interest": flt(total_interest, 2),
		"rate_of_interest": rate,
		"loan_amount": amount,
		"repayment_periods": periods,
	}