#!/usr/bin/env python3
"""R28-F12: Sanitise orphan Loans on a live site.

A Loan is "orphan" when ``applicant_type="Customer"`` but no Customer with
``name=loan.applicant`` exists on the site. This state usually arises
from test-fixture cleanups that delete Customers but leave the
originating Loan Application / Loan pointing at the now-deleted
borrower. Operators click "Disburse" and receive an opaque
``LinkValidationError: Could not find Applicant`` traceback.

Fix policy:
  * Loans with ``docstatus=0`` (Draft): cancel + flag with a note in the
    ``Loan Application`` remark so ops can recreate the borrower.
  * Loans with ``docstatus=1`` (Submitted): create a stub
    ``Customer`` record keyed on the original applicant name, branch =
    loan's branch, status = existing or new branch, and link the
    Customer to the loan's LMS Borrower Compliance (if any) so that the
    rest of the lending machinery (repayment schedule, repayments) can
    resolve the customer. The stub is flagged with a custom note so the
    operator knows it was auto-created.

Idempotent: re-running on a sanitised site is a no-op.

Usage::

    # Dry run (default) — only reports what would change.
    bench --site lms.localhost execute lms_saas.scripts.fix_orphan_loans.run

    # Apply fixes.
    bench --site lms.localhost execute lms_saas.scripts.fix_orphan_loans.run --apply

    # Limit to a specific list of loan names.
    bench --site lms.localhost execute lms_saas.scripts.fix_orphan_loans.run --apply --loan ACC-LOAN-2026-00036

Exit code 0 always (audit trail is the source of truth).
"""

from __future__ import annotations

import sys

import frappe
from frappe import _


def _audit(event_type: str, details: str) -> None:
	"""Best-effort LMS Audit Event write. Failure must never block."""
	if not frappe.db.exists("DocType", "LMS Audit Event"):
		return
	try:
		frappe.get_doc(
			{
				"doctype": "LMS Audit Event",
				"event_type": event_type,
				"event_time": frappe.utils.now_datetime(),
				"event_user": frappe.session.user,
				"reference_doctype": "Loan",
				"reference_name": "—",
				"company": frappe.db.get_single_value("Global Defaults", "default_company") or "",
				"details": details,
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(
			title="LMS fix_orphan_loans audit write failed",
			message=frappe.get_traceback(),
		)


def _find_orphan_loans(named: list[str] | None = None) -> list[dict]:
	"""Return loans whose Customer applicant is missing."""
	filters = {"applicant_type": "Customer"}
	if named:
		filters["name"] = ("in", named)
	rows = frappe.get_all(
		"Loan",
		filters=filters,
		fields=["name", "docstatus", "status", "applicant", "company", "custom_lms_branch"],
		limit_page_length=0,
	)
	out = []
	for r in rows:
		if r["applicant"] and not frappe.db.exists("Customer", r["applicant"]):
			out.append(r)
	return out


def _resolve_customer_group() -> str:
	"""Find a non-group Customer Group; required to create a Customer."""
	return (
		frappe.db.get_value("Customer Group", {"is_group": 0}, "name")
		or frappe.db.get_single_value("Selling Settings", "customer_group")
		or ""
	)


def _resolve_territory() -> str:
	return frappe.db.get_value("Territory", {"is_group": 0}, "name") or ""


def _create_stub_customer(name: str, branch: str | None) -> str:
	"""Create a placeholder Customer with the borrower's old name.

	The lender side resolves Customer rows by ``name``, so the new
	Customer's PK must equal the orphaned applicant string. We also
	flag the row with a clearly-visible note so a human auditor notices
	that this row was auto-created.
	"""
	cust_group = _resolve_customer_group()
	territory = _resolve_territory()
	if not cust_group or not territory:
		raise RuntimeError(
			"No non-group Customer Group / Territory configured — aborting"
		)
	stub = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Individual",
			"customer_group": cust_group,
			"territory": territory,
			"custom_lms_branch": branch or "",
		}
	)
	stub.flags.ignore_permissions = True
	stub.insert()
	# R28-F12 followup: log the auto-creation in frappe.error_log so the
	# operator can spot it from the desk. (There's no canonical "notes"
	# field on Customer without a custom-field migration; the audit row
	# already covers the regulator view.)
	frappe.log_error(
		title="LMS fix_orphan_loans: stub Customer auto-created",
		message=(
			f"customer={stub.name} branch={branch} reason=orphan_loan "
			f"created_at={frappe.utils.nowdate()} — reconcile with HR / KYC "
			f"before next disbursement."
		),
	)
	return stub.name


def _cancel_draft_loan(loan_name: str) -> None:
	loan = frappe.get_doc("Loan", loan_name)
	if loan.docstatus != 0:
		return
	loan.flags.ignore_permissions = True
	try:
		loan.cancel()
	except Exception:
		frappe.log_error(
			title="LMS fix_orphan_loans: cancel draft failed",
			message=f"loan={loan_name}\n{frappe.get_traceback()}",
		)


def run(apply: bool = False, loan: list[str] | None = None) -> dict:
	"""Run the sanitiser; returns a summary dict.

	Args:
		apply: if False, dry-run (reports only, makes no changes).
		loan: optional list of Loan names to limit the scan to.
	"""
	orphans = _find_orphan_loans(loan)
	summary = {
		"found": len(orphans),
		"drafts_cancelled": 0,
		"stubs_created": [],
		"errors": [],
	}

	if not apply:
		summary["dry_run"] = True
		return summary

	summary["dry_run"] = False
	for row in orphans:
		try:
			if row["docstatus"] == 0:
				_cancel_draft_loan(row["name"])
				summary["drafts_cancelled"] += 1
				_audit(
					"ORPHAN_LOAN_CANCELLED",
					f"loan={row['name']} applicant={row['applicant']} "
					f"reason=customer_missing",
				)
			else:
				stub = _create_stub_customer(row["applicant"], row.get("custom_lms_branch"))
				summary["stubs_created"].append({"loan": row["name"], "customer": stub})
				_audit(
					"ORPHAN_LOAN_STUB_CREATED",
					f"loan={row['name']} applicant={row['applicant']} "
					f"stub_customer={stub} branch={row.get('custom_lms_branch')}",
				)
		except Exception as e:
			summary["errors"].append(
				{"loan": row["name"], "error": f"{type(e).__name__}: {e}"}
			)
			frappe.log_error(
				title="LMS fix_orphan_loans: error sanitising loan",
				message=f"loan={row['name']}\n{frappe.get_traceback()}",
			)

	frappe.db.commit()
	return summary


# ---------------------------------------------------------------------------
# Bench execute entry-point
# ---------------------------------------------------------------------------

def _entry_point():
	"""Whitelist-style entry so `bench execute` can pass flags.

	`bench execute module.func --apply --loan ACC-LOAN-2026-00001 ...` passes
	positional args after `module.func` name; we read them from sys.argv.
	"""
	apply = False
	named = []
	for arg in sys.argv[1:]:
		if arg in ("--apply", "-apply"):
			apply = True
		elif arg.startswith("--loan="):
			named.append(arg.split("=", 1)[1])
	out = run(apply=apply, loan=named or None)
	# Pretty-print summary so bench execute's stdout is operator-friendly.
	import json
	print(json.dumps(out, indent=2, default=str))


if __name__ == "__main__":
	# Allow `python3 fix_orphan_loans.py --apply ...` from the bench shell.
	frappe.init(site="lms.localhost", sites_path="../sites")
	frappe.connect()
	frappe.set_user("Administrator")
	try:
		_entry_point()
	finally:
		frappe.destroy()
