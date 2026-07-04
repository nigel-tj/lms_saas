"""Configurable credit policy rules engine."""

from __future__ import annotations

import frappe
from frappe.utils import flt


def evaluate_credit_policy(doc, method=None):
	"""Evaluate LMS Credit Policy rules before bureau check."""
	if frappe.flags.in_install:
		return

	policy_name = _resolve_policy(doc)
	if not policy_name:
		return

	policy = frappe.get_doc("LMS Credit Policy", policy_name)
	if not policy.enabled or not policy.rules:
		return

	context = _build_context(doc)
	failures = []
	refers = []

	for rule in policy.rules:
		actual = flt(context.get(rule.rule_field, 0))
		threshold = flt(rule.threshold)
		passed = _compare(actual, rule.operator, threshold)
		if passed:
			continue
		if rule.action == "Fail":
			failures.append(f"{rule.rule_field} {rule.operator} {threshold} (actual {actual})")
		elif rule.action == "Refer":
			refers.append(f"{rule.rule_field} {rule.operator} {threshold} (actual {actual})")

	if failures:
		frappe.throw("Credit policy failed: " + "; ".join(failures))

	if refers:
		_create_refer_todo(doc, refers)


def _resolve_policy(doc):
	if doc.get("loan_product"):
		name = frappe.db.get_value(
			"LMS Credit Policy",
			{"loan_product": doc.loan_product, "enabled": 1},
			"name",
		)
		if name:
			return name
	return frappe.db.get_value("LMS Credit Policy", {"enabled": 1, "loan_product": ("is", "not set")}, "name")


def _build_context(doc):
	compliance = frappe.db.get_value(
		"LMS Borrower Compliance",
		{"customer": doc.applicant},
		["credit_score", "debt_to_income_ratio"],
		as_dict=True,
	) or {}

	exposure = frappe.db.sql(
		"""
		select coalesce(sum(total_payment - total_amount_paid), 0)
		from `tabLoan`
		where applicant = %s and docstatus = 1 and status in ('Disbursed', 'Active', 'Partially Disbursed')
		""",
		doc.applicant,
	)[0][0]

	coverage = 0.0
	try:
		from lms_saas.api.collateral import get_collateral_coverage

		cov = get_collateral_coverage(doc)
		coverage = flt(cov.get("coverage_ratio") or 0)
	except Exception:
		pass

	return {
		"credit_score": flt(compliance.get("credit_score")),
		"debt_to_income_ratio": flt(compliance.get("debt_to_income_ratio")),
		"loan_amount": flt(doc.loan_amount),
		"max_exposure": flt(exposure) + flt(doc.loan_amount),
		"collateral_coverage": coverage,
	}


def _compare(actual, operator, threshold):
	if operator == ">=":
		return actual >= threshold
	if operator == "<=":
		return actual <= threshold
	if operator == ">":
		return actual > threshold
	if operator == "<":
		return actual < threshold
	return actual == threshold


def _create_refer_todo(doc, reasons):
	try:
		frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": f"Credit policy refer: {doc.name} — " + "; ".join(reasons),
				"reference_type": doc.doctype,
				"reference_name": doc.name,
				"priority": "High",
				"status": "Open",
			}
		).insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="LMS credit refer todo failed", message=frappe.get_traceback())
