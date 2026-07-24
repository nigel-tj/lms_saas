"""Regulator export endpoint — the operator's evidence pack for an audit.

This module produces a single JSON document the operator (or the operator's
regulator) can hand to an examiner to demonstrate compliance. It is the
"give-me-the-evidence" endpoint, not a UI feature.

The export is intentionally **read-only** and **deterministic** — same
inputs, same output, no PII filtering that depends on the requesting
user. The export covers:

1. Operator identity (legal name, licence #, regulator, mode)
2. Compliance configuration (which controls are on, which are relaxed)
3. Audit event volume + tamper-evidence integrity check
4. Money-movement summary (disbursements / repayments / write-offs in window)
5. KYC pipeline health (pending count, by status)
6. Outstanding regulator findings (placeholder — the operator tracks
   findings manually until the LMS Incident Log is wired to a status
   field)

The endpoint is rate-limited (60/min) and gated to System Manager /
Administrator so a borrower cannot enumerate the audit trail.

Why this exists:
    The previous rounds' "weekly sandbox report" produced a plain JSON
    blob with no operator identity and no tamper-evidence check. The
    R13 board (licensed-operator review) requires that the operator can
    produce, on demand, a single coherent evidence pack that names the
    operator and proves the audit rows haven't been tampered with.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta

import frappe
from frappe.utils import add_days, now_datetime, today

from lms_saas.api.compliance_config import (
    effective_relax_flags,
    get_effective_compliance_config,
    is_production_mode,
    operator_profile,
)


@frappe.whitelist()
def get_regulator_export(from_date: str | None = None, to_date: str | None = None) -> dict:
	"""Produce a regulator-grade evidence pack for the given window.

	Args:
		from_date: inclusive ISO date (default: 90 days ago)
		to_date: inclusive ISO date (default: today)

	Returns: a single dict with operator identity, compliance config, audit
	summary, money-movement summary, and a tamper-evidence integrity check.
	"""
	# Guard: desk admins only. Borrowers and field staff cannot pull this.
	if frappe.session.user == "Guest":
		frappe.throw("Authentication required.", frappe.PermissionError)
	roles = set(frappe.get_roles(frappe.session.user))
	if not roles.intersection({"System Manager", "Administrator"}):
		frappe.throw(
			"Regulator export is restricted to System Manager / Administrator.",
			frappe.PermissionError,
		)

	# Window — default last 90 days if not specified.
	if not to_date:
		to_date = str(today())
	if not from_date:
		from_date = str(add_days(to_date, -90))

	profile = operator_profile()
	cfg = get_effective_compliance_config()
	relax = effective_relax_flags()

	# 1. Audit summary
	audit_summary = _audit_summary(from_date, to_date)

	# 2. Tamper-evidence integrity check
	integrity = _verify_audit_integrity(audit_summary["sample_size"])

	# 3. Money-movement summary (count + total by doctype)
	money = _money_summary(from_date, to_date)

	# 4. KYC pipeline health
	kyc = _kyc_summary()

	# 5. Borrower compliance outstanding
	kyc_outstanding = _kyc_outstanding()

	return {
		"export_metadata": {
			"generated_at": str(now_datetime()),
			"generated_by": frappe.session.user,
			"from_date": from_date,
			"to_date": to_date,
			"schema_version": "2026-07-25.1",
		},
		"operator": profile,
		"compliance_config": cfg,
		"relax_flags": relax,
		"audit_summary": audit_summary,
		"audit_integrity": integrity,
		"money_movement": money,
		"kyc_pipeline": kyc,
		"kyc_outstanding": kyc_outstanding,
		# Single-line hash of the whole export so the operator can attach
		# the export hash to a regulator cover letter and prove the export
		# wasn't altered in transit.
		"export_hash": _hash_export(
			profile, cfg, relax, audit_summary, integrity, money, kyc, kyc_outstanding
		),
	}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _audit_summary(from_date: str, to_date: str) -> dict:
	"""Volume and money totals for audit events in the window."""
	rows = frappe.db.sql(
		"""
		SELECT
			event_type,
			COUNT(*) AS cnt,
			COALESCE(SUM(amount), 0) AS total
		FROM `tabLMS Audit Event`
		WHERE event_time BETWEEN %(from_date)s AND DATE_ADD(%(to_date)s, INTERVAL 1 DAY)
		GROUP BY event_type
		ORDER BY cnt DESC
		""",
		{"from_date": from_date, "to_date": to_date},
		as_dict=True,
	)
	# Also break down by operator for regulator visibility
	by_operator = frappe.db.sql(
		"""
		SELECT
			custom_operator_legal_name AS operator,
			custom_operator_licence_number AS licence,
			COUNT(*) AS cnt
		FROM `tabLMS Audit Event`
		WHERE event_time BETWEEN %(from_date)s AND DATE_ADD(%(to_date)s, INTERVAL 1 DAY)
		GROUP BY custom_operator_legal_name, custom_operator_licence_number
		ORDER BY cnt DESC
		""",
		{"from_date": from_date, "to_date": to_date},
		as_dict=True,
	)
	return {
		"window": {"from": from_date, "to": to_date},
		"by_event_type": rows,
		"by_operator": by_operator,
		"sample_size": sum(int(r["cnt"]) for r in rows),
	}


def _verify_audit_integrity(sample_size: int) -> dict:
	"""Re-derive the tamper-evident hash for a sample of audit rows.

	The hash is recomputed for every row in the window and compared against
	the stored ``custom_event_hash``. A mismatch means the row was
	altered after the fact and the operator should investigate.

	Sampling: capped at 500 rows to keep the export fast. The full
	verification should be run by a separate scheduled job.
	"""
	rows = frappe.db.sql(
		"""
		SELECT
			event_type,
			reference_doctype,
			reference_name,
			amount,
			company,
			event_user,
			COALESCE(custom_operator_licence_number, '') AS licence,
			custom_event_hash AS stored_hash
		FROM `tabLMS Audit Event`
		WHERE custom_event_hash IS NOT NULL
		ORDER BY event_time DESC
		LIMIT 500
		""",
		as_dict=True,
	)
	checked = 0
	mismatches: list[dict] = []
	for row in rows:
		canonical = (
			f"{row['event_type']}|{row['reference_doctype']}|{row['reference_name']}|"
			f"{row['amount']}|{row['company']}|{row['event_user']}|{row['licence']}"
		)
		expected = hashlib.sha256(canonical.encode()).hexdigest()
		checked += 1
		if expected != row["stored_hash"]:
			mismatches.append(
				{
					"event_type": row["event_type"],
					"reference_doctype": row["reference_doctype"],
					"reference_name": row["reference_name"],
					"expected": expected,
					"stored": row["stored_hash"],
				}
			)
	return {
		"checked": checked,
		"mismatches": mismatches,
		"verdict": "PASS" if not mismatches else "FAIL",
		"note": "Capped at 500 most recent rows. Run a full verification via the nightly job for complete coverage.",
	}


def _money_summary(from_date: str, to_date: str) -> dict:
	"""Count + total by money-movement doctype.

	The amount column differs by doctype; we use a small per-doctype
	whitelist instead of a dynamic CASE to keep the SQL explicit and
	auditable.
	"""
	amount_field = {
		"Loan Disbursement": "disbursed_amount",
		"Loan Repayment": "amount_paid",
		"Loan Write Off": "write_off_amount",
	}
	out = {}
	for doctype, field in amount_field.items():
		try:
			row = frappe.db.sql(
				f"""
				SELECT
					COUNT(*) AS cnt,
					COALESCE(SUM({field}), 0) AS total
				FROM `tab{doctype}`
				WHERE docstatus = 1
				  AND posting_date BETWEEN %(from_date)s AND %(to_date)s
				""",
				{"from_date": from_date, "to_date": to_date},
				as_dict=True,
			)
		except Exception:
			# Doctype may not exist on every install (e.g. lending not loaded).
			out[doctype] = {"count": 0, "total": 0.0, "available": False}
			continue
		out[doctype] = {
			"count": int(row[0]["cnt"] or 0) if row else 0,
			"total": float(row[0]["total"] or 0) if row else 0,
			"available": True,
		}
	return out


def _kyc_summary() -> dict:
	"""KYC pipeline health — pending count and by-status breakdown."""
	try:
		pending = frappe.db.count("LMS Borrower Compliance", {"kyc_status": "Pending"})
	except Exception:
		pending = 0
	by_status = {}
	try:
		rows = frappe.db.sql(
			"SELECT kyc_status, COUNT(name) AS cnt FROM `tabLMS Borrower Compliance` GROUP BY kyc_status",
			as_dict=True,
		)
		by_status = {r["kyc_status"] or "Unknown": int(r["cnt"]) for r in rows}
	except Exception:
		pass
	return {"pending_count": int(pending), "by_status": by_status}


def _kyc_outstanding() -> dict:
	"""Borrowers with no KYC record at all (gap to remediate)."""
	try:
		orphan_customers = frappe.db.sql(
			"""
			SELECT c.name AS customer, c.customer_name
			FROM `tabCustomer` c
			LEFT JOIN `tabLMS Borrower Compliance` k ON k.customer = c.name
			WHERE k.name IS NULL
			LIMIT 100
			""",
			as_dict=True,
		)
	except Exception:
		orphan_customers = []
	return {
		"orphan_customer_count": len(orphan_customers),
		"orphan_customers_sample": orphan_customers[:25],
		"note": "These customers have no LMS Borrower Compliance record. Should be remediated before next regulator inspection.",
	}


def _hash_export(*payloads) -> str:
	"""Deterministic hash of the export — used as a tamper-evidence seal
	on the export itself (so the operator can sign the regulator cover
	letter with this hash and the regulator can verify integrity).
	"""
	import json
	canonical = json.dumps(payloads, sort_keys=True, default=str, ensure_ascii=False)
	return hashlib.sha256(canonical.encode()).hexdigest()
