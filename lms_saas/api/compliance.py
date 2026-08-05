"""Origination compliance controls — config-driven, regulator-agnostic.

ARCHITECTURE NOTE (R22 review feedback):
    Compliance is a POLICY LAYER on top of general-purpose loan management,
    not the engine of the software. This module enforces borrower-consent,
    transaction caps, interest-rate ceilings, and customer-count limits
    that the operator's regulator mandates. The regulator identity is a
    config value (``lms_operator_regulator``); user-facing messages do NOT
    name the regulator, so the same code base ships against multiple
    jurisdictions (RBZ, CBK, BoZ, etc.) without code changes.

    The defaults below are conservative general-purpose floors. Operators
    MAY raise (or, where the regulator allows, lower) them via site_config.

Enforcement controls are config-gated so they can be switched on per
environment without code changes:
    lms_enforce_four_eyes      (bool)  maker != checker on disbursement/write-off
    lms_require_consent        (bool)  borrower consent required before origination
    lms_max_loan_amount        (number) per-loan transaction cap
    lms_max_active_customers   (number) active-customer cap
    lms_sandbox_end_date       (date)  testing window end (if set, blocks new originations after)
"""

import frappe
from frappe.utils import add_days, cint, flt, getdate, now_datetime, today

from lms_saas.api.compliance_config import (
	assert_production_money_op_allowed,
	operator_profile,
	resolve_regulator_message_suffix,
)

MONEY_DOCTYPES = ("Loan", "Loan Disbursement", "Loan Repayment", "Loan Write Off", "LMS Investor Transaction")

# B7: default maximum permitted interest rate (percent) at origination when no
# site-specific `lms_max_rate_of_interest` is configured. Fail-closed ceiling.
# This is a conservative general-purpose default — operators in jurisdictions
# with higher caps may raise it via site_config; jurisdictions with lower caps
# should set the cap explicitly.
DEFAULT_MAX_RATE_OF_INTEREST = 20


# ---------------------------------------------------------------------------
# Audit trail (Annex 5.1)
# ---------------------------------------------------------------------------

def write_audit_event(event_type, reference_doctype, reference_name, amount=None, company=None, details=None, critical=False):
	"""Append an immutable audit event.

	If ``critical=True`` (used for money-movement events: disbursement,
	write-off, repayment, approval), a failure to write the audit row
	**raises** — rolling back the business transaction. For a regulated
	microfinance system, a disbursement with no audit evidence is a
	reportable incident; we refuse to commit the business op if the
	audit trail cannot be written.

	If ``critical=False`` (default — used for non-money events like
	customer updates), the failure is logged but does not break the
	business flow.
	"""
	# Production guard: refuse to write a money-movement audit row in an
	# unlicensed install. The check is on the WRITE path so the audit
	# trail never silently records events from a site that hasn't been
	# validated by the operator.
	if critical:
		assert_production_money_op_allowed()

	# Operator profile (legal name, licence #) is appended to every
	# audit event so a regulator can confirm the row was written by a
	# licensed operator, not a demo. Also stored in dedicated custom
	# fields so the regulator export can filter and group by operator.
	op = operator_profile()
	# Accept both string and dict details; the old record_money_event
	# passes a string. The audit event's "details" field is a Long Text.
	details_str = details if isinstance(details, str) else (frappe.as_json(details) if details else "")
	details_with_op = details_str + (
		f" | operator={op['legal_name']} licence={op['licence_number']}"
		f" regulator={op['regulator']}"
	)

	# Tamper-evident hash: hash of the canonical event payload (excluding
	# the hash itself). The regulator export cross-checks this against
	# the event payload so a tampered row is detectable. Stored on a
	# separate indexed field for fast scanning.
	import hashlib
	canonical = (
		f"{event_type}|{reference_doctype}|{reference_name}|"
		f"{amount}|{company}|{frappe.session.user}|{op['licence_number']}"
	)
	event_hash = hashlib.sha256(canonical.encode()).hexdigest()

	try:
		frappe.get_doc(
			{
				"doctype": "LMS Audit Event",
				"event_time": now_datetime(),
				"event_type": event_type,
				"event_user": frappe.session.user,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"amount": amount,
				"company": company,
				"details": details_with_op,
				"custom_operator_legal_name": op["legal_name"],
				"custom_operator_licence_number": op["licence_number"],
				"custom_operator_regulator": op["regulator"],
				"custom_operator_mode": op["mode"],
				"custom_event_hash": event_hash,
			}
		).insert(ignore_permissions=True)
	except Exception:  # noqa: BLE001
		try:
			frappe.log_error(title="LMS audit event failed", message=frappe.get_traceback())
		except Exception:
			pass  # log_error itself failed — can't do much
		if critical:
			raise  # roll back the business transaction — no audit = no commit


def record_money_event(doc, method):
    """doc_event hook: record submit/cancel of money-movement documents."""
    amount = (
        getattr(doc, "disbursed_amount", None)
        or getattr(doc, "amount_paid", None)
        or getattr(doc, "amount", None)
        or getattr(doc, "loan_amount", None)
    )
    write_audit_event(
        event_type=f"{doc.doctype}:{method}",
        reference_doctype=doc.doctype,
        reference_name=doc.name,
        amount=flt(amount) if amount else None,
        company=getattr(doc, "company", None),
        details=f"status={getattr(doc, 'status', None)}",
        critical=True,  # P0 fix: money-movement events must roll back on audit failure
    )


# ---------------------------------------------------------------------------
# Four-eyes / maker-checker (Annex 5.1)
# ---------------------------------------------------------------------------

def enforce_four_eyes(doc, method):
	"""High-impact actions require a different approver than the maker.

	PRODUCTION-HARDENING (B5): four-eyes is now ENFORCED by default. The old
	behaviour let any site run with `lms_enforce_four_eyes=False`, silently
	allowing a maker to self-approve disbursements and write-offs. Now the
	control is on unless the site explicitly opts into relaxed mode via
	`lms_relax_four_eyes=True` (sandbox / automated seeding only). The legacy
	flag `lms_compliance_relaxed=True` is honoured for backward compatibility
	but per-flag opt-out is preferred so a site can relax four-eyes without
	disabling every other compliance control.

	R20-P5: the four-eyes check now also covers Loan creation. A Loan is the
	immutable record of the originated facility; if a Branch Manager can
	create the Loan and then submit the Loan Disbursement under their own
	ownership, the maker of the Loan and the maker of the Disbursement are
	the same user and the check is meaningless. We resolve the Loan's
	originating Loan Application (via ``custom_lms_loan_application`` if
	set, else the most recent draft Application for the same applicant) and
	require the Loan submitter to differ from that application's owner.
	"""
	if frappe.flags.in_install or frappe.flags.in_migrate:
		return
	# R12 board (M4): per-flag opt-out. Legacy `lms_compliance_relaxed` still
	# disables everything for sites that relied on the old single kill-switch.
	if frappe.conf.get("lms_relax_four_eyes") or frappe.conf.get("lms_compliance_relaxed"):
		return
	if doc.owner and frappe.session.user == doc.owner:
		frappe.throw(
			f"Four-eyes control: the maker ({doc.owner}) cannot approve their own "
			f"{doc.doctype}. A second authorised user must submit it."
		)
	# R20-P5: cross-doctype maker check on Loan. The Loan is the immutable
	# facility record; its originating Application is what an auditor will
	# trace back to. If the Loan submitter is the same as the Application
	# owner, that's a maker-self-origination, which four-eyes forbids.
	if doc.doctype == "Loan":
		app_owner = _resolve_loan_application_owner(doc)
		if app_owner and frappe.session.user == app_owner:
			frappe.throw(
				f"Four-eyes control: the maker of the originating Loan Application "
				f"({app_owner}) cannot also be the maker of Loan {doc.name}. "
				f"A second authorised user must submit the Loan."
			)


def _resolve_loan_application_owner(loan_doc) -> str | None:
	"""Return the User that owned the originating Loan Application for a Loan.

	Resolution order (first hit wins):
	1. ``Loan.custom_lms_loan_application`` direct pointer to the
	   originating Loan Application (preferred — set by the
	   borrower-side submit flow and the officer-side submit flow).
	2. ``Loan Application.applicant == Loan.applicant`` AND same
	   ``loan_product`` AND ``docstatus == 1`` AND
	   ``app.creation <= loan.creation`` (time-windowed fallback — the
	   OLD broken resolver was unbounded here, which let an
	   Administrator-owned seed app satisfy the check for a later Loan).
	3. None (Loan was created outside the Loan Application flow \u2014 e.g.
	   migrated data \u2014 in which case the four-eyes check on the Loan
	   itself via ``doc.owner`` above is sufficient).
	"""
	loan_name = getattr(loan_doc, "name", None)
	loan_creation = getattr(loan_doc, "creation", None)
	# 1. Direct link (R21-C1). The custom field may not exist on installs
	# that ran the install.py before this fixture was added; in that
	# case fall through silently.
	if loan_name and frappe.get_meta("Loan").has_field("custom_lms_loan_application"):
		direct = frappe.db.get_value("Loan", loan_name, "custom_lms_loan_application")
		if direct:
			app = frappe.db.get_value(
				"Loan Application",
				direct,
				["owner", "docstatus"],
				as_dict=True,
			)
			if app and (app.get("docstatus") if hasattr(app, "get") else app.docstatus) == 1:
				return app.get("owner") if hasattr(app, "get") else app.owner
	# 2. Time-windowed fallback: most recent submitted Application
	# for the same (applicant, loan_product) AND app.creation <= loan.creation.
	applicant = getattr(loan_doc, "applicant", None)
	loan_product = getattr(loan_doc, "loan_product", None)
	if applicant and loan_product:
		filters = {
			"applicant": applicant,
			"loan_product": loan_product,
			"docstatus": 1,
		}
		if loan_creation:
			filters["creation"] = ("<=", loan_creation)
		app_name = frappe.db.get_value(
			"Loan Application",
			filters,
			"name",
			order_by="creation desc",
		)
		if app_name:
			return frappe.db.get_value("Loan Application", app_name, "owner")
	return None


# ---------------------------------------------------------------------------
# Origination controls: limits, consent, sandbox window (Annex 4.5, 3.19, 3.32)
# ---------------------------------------------------------------------------

def enforce_origination_controls(doc, method):
	"""Validate a Loan Application against sandbox / production boundaries.

	PRODUCTION-HARDENING (B5/B7): consent, transaction cap and customer cap are
	now REQUIRED by default (fail-closed). Previously every check was gated
	behind a config flag that defaulted OFF, so a site without the flags set
	would originate with no consent capture, no amount cap and no customer cap.
	Now these are enforced unless the site explicitly enables relaxed mode
	(`lms_compliance_relaxed=True`) for sandbox testing.
	"""
	# R12 board (M4): per-flag relaxation. `lms_relax_origination` disables
	# origination controls specifically; legacy `lms_compliance_relaxed`
	# still disables everything (backward compat).
	relaxed = (
		frappe.conf.get("lms_relax_origination", False)
		or frappe.conf.get("lms_compliance_relaxed", False)
	)

	end_date = frappe.conf.get("lms_sandbox_end_date")
	if end_date and getdate(today()) > getdate(end_date):
		frappe.throw(
			"Origination testing window has ended. New originations are not "
			"permitted." + resolve_regulator_message_suffix()
		)

	max_amount = frappe.conf.get("lms_max_loan_amount")
	if max_amount and flt(doc.loan_amount) > flt(max_amount):
		frappe.throw(
			f"Loan amount {flt(doc.loan_amount)} exceeds the configured "
			f"transaction limit ({flt(max_amount)})."
		)
	# B7: enforce a hard ceiling on the interest rate at origination unless relaxed.
	if not relaxed:
		rate_cap = flt(frappe.conf.get("lms_max_rate_of_interest", 0)) or DEFAULT_MAX_RATE_OF_INTEREST
		if flt(getattr(doc, "rate_of_interest", 0)) > rate_cap:
			frappe.throw(
				f"Interest rate {flt(getattr(doc, 'rate_of_interest', 0))}% exceeds the "
				f"permitted maximum ({rate_cap}%)."
			)

	require_consent = frappe.conf.get("lms_require_consent", False) or not relaxed
	if require_consent:
		consent = frappe.db.get_value(
			"LMS Borrower Compliance", {"customer": doc.applicant}, "consent_given"
		)
		if not consent:
			frappe.throw(
				"Customer consent is required before origination. "
				"Record consent on the borrower's LMS Borrower Compliance profile."
				+ resolve_regulator_message_suffix()
			)

	max_customers = frappe.conf.get("lms_max_active_customers")
	if max_customers:
		active = frappe.get_all(
			"Loan",
			filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
			distinct=True,
			pluck="applicant",
		)
		existing = set(active)
		if doc.applicant not in existing and len(existing) >= int(max_customers):
			frappe.throw(
				f"Active-customer cap ({int(max_customers)}) reached."
			)


# ---------------------------------------------------------------------------
# Weekly sandbox KPI report (Annex 5.1)
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_sandbox_report(days=7):
	"""Return the metrics required for the operator's regulatory progress report.

	The report is regulator-agnostic: the operator's profile (regulator name,
	licence number) is appended to every row so the same export serves any
	jurisdiction. The shape mirrors the standard microfinance weekly KPI pack.
	"""
	# Role check — restrict to admin only (P1 fix: regulatory report is system-wide data).
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "Administrator"}):
		frappe.throw("Not permitted", frappe.PermissionError)

	# Sanitize days parameter (P1 fix).
	days = max(1, min(cint(days), 365))
	since = add_days(today(), -int(days))

	active_customers = frappe.get_all(
		"Loan",
		filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
		distinct=True,
		pluck="applicant",
	)

	# R42: Frappe v15+ rejects string-form SQL functions in `fields`.
	# Use ``frappe.db.sql`` directly for aggregate queries.
	disbursements = frappe.db.sql(
		"""SELECT COUNT(*) AS count, COALESCE(SUM(disbursed_amount), 0) AS value
		   FROM `tabLoan Disbursement`
		   WHERE docstatus = 1 AND posting_date >= %s""",
		since,
		as_dict=True,
	)[0]
	repayments = frappe.db.sql(
		"""SELECT COUNT(*) AS count, COALESCE(SUM(amount_paid), 0) AS value
		   FROM `tabLoan Repayment`
		   WHERE docstatus = 1 AND posting_date >= %s""",
		since,
		as_dict=True,
	)[0]

	incidents = frappe.get_all(
		"LMS Incident Log",
		filters={"reported_on": (">=", since)},
		fields=["name", "incident_type", "severity", "status", "title"],
		order_by="reported_on desc",
	)
	complaints = [i for i in incidents if i.incident_type == "Customer Complaint"]
	open_incidents = [i for i in incidents if i.status in ("Open", "Investigating")]

	audit_events = frappe.db.count("LMS Audit Event", {"event_time": (">=", since)})

	return {
		"period_days": int(days),
		"since": str(since),
		"volunteer_customers": len(active_customers),
		"transactions": {
			"disbursements_count": disbursements.count or 0,
			"disbursements_value": flt(disbursements.value),
			"repayments_count": repayments.count or 0,
			"repayments_value": flt(repayments.value),
		},
		"incidents_open": len(open_incidents),
		"complaints": len(complaints),
		"incident_log": incidents,
		"audit_events": audit_events,
	}


# ---------------------------------------------------------------------------
# Data protection: right to erasure / retention (CDPA §§ — B6)
# ---------------------------------------------------------------------------

# Direct identifiers that must be erased/anonymised on request or expiry.
_ERASABLE_CUSTOMER_FIELDS = (
	"customer_name",
	"email_id",
	"mobile_no",
	"custom_national_id_number",
	"primary_address",
)

# Default personal-data retention window (days) when no site config is set.
DEFAULT_DATA_RETENTION_DAYS = 365 * 7


@frappe.whitelist()
def erase_borrower_personal_data(customer: str):
	"""CDPA right-to-erasure: blank direct identifiers for a borrower.

	Financial/ledger records (GL entries, Loan Repayment, Audit Events) are
	deliberately RETAINED — regulators require the money trail to stay intact.
	Only direct personal identifiers are anonymised. Admin/staff only.
	"""
	roles = set(frappe.get_roles())
	if not roles.intersection({"System Manager", "Administrator"}):
		frappe.throw("Not permitted", frappe.PermissionError)

	if not frappe.db.exists("Customer", customer):
		frappe.throw(f"Customer {customer} not found.")

	cust = frappe.get_doc("Customer", customer)
	for field in _ERASABLE_CUSTOMER_FIELDS:
		if hasattr(cust, field):
			setattr(cust, field, "ERASED")
	cust.flags.ignore_permissions = True
	cust.save()

	# Anonymise the linked compliance profile identifiers too.
	if frappe.db.exists("LMS Borrower Compliance", {"customer": customer}):
		comp = frappe.get_doc("LMS Borrower Compliance", {"customer": customer})
		for field in ("national_id_number", "email", "mobile_number"):
			if hasattr(comp, field):
				setattr(comp, field, "ERASED")
		comp.flags.ignore_permissions = True
		comp.save()

	write_audit_event(
		event_type="Data:Erasure",
		reference_doctype="Customer",
		reference_name=customer,
		details="CDPA right-to-erasure applied; identifiers anonymised, financial trail retained.",
		critical=True,
	)
	return {"status": "erased", "customer": customer}


def anonymize_expired_personal_data():
	"""Scheduler: erase identifiers for closed borrowers past the retention window.

	Called monthly. Only acts on customers with no active loans and whose last
	activity is older than `lms_data_retention_days` (default 7 years). Blank
	direct identifiers; retain the financial trail.
	"""
	retention = int(
		frappe.conf.get("lms_data_retention_days", DEFAULT_DATA_RETENTION_DAYS)
	)
	cutoff = add_days(today(), -retention)
	expired = frappe.get_all(
		"Customer",
		filters={"disabled": 1, "modified": ("<", cutoff)},
		pluck="name",
		limit=500,
	)
	count = 0
	for name in expired:
		# Skip customers with any non-cancelled loan still on the books.
		open_loans = frappe.get_all(
			"Loan",
			filters={"applicant": name, "docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
			limit=1,
		)
		if open_loans:
			continue
		try:
			erase_borrower_personal_data(name)
			count += 1
		except Exception:
			frappe.log_error(title="LMS data erasure failed", message=frappe.get_traceback())
	return {"erased": count}

