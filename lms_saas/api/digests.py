"""Morning digest data and delivery for branch oversight."""

from __future__ import annotations

import frappe
from frappe.utils import add_days, flt, getdate, today

from lms_saas.api.collections import get_collections_config
from lms_saas.api.dashboard import _collections_trend, _portfolio_metrics
from lms_saas.utils.charts import render_email_bar_chart, rows_from_risk_buckets


def get_digest_recipients() -> list[str]:
	"""Explicit list or all enabled LMS Branch Manager users."""
	raw = (frappe.conf.get("lms_digest_recipients") or "").strip()
	if raw:
		from lms_saas.utils.email import _normalize_recipients

		return _normalize_recipients([e.strip() for e in raw.split(",") if e.strip()])

	emails = []
	for user in frappe.get_all(
		"Has Role",
		filters={"role": "System Manager", "parenttype": "User"},
		pluck="parent",
	):
		if user in ("Administrator", "Guest"):
			continue
		email = frappe.db.get_value("User", user, "email")
		if email:
			emails.append(email)
	return list(dict.fromkeys(emails))


def get_kyc_pending_rows(alert_days: int | None = None) -> list[dict]:
	"""Borrowers with KYC still pending beyond alert threshold."""
	config = get_collections_config()
	days = alert_days if alert_days is not None else config["kyc_pending_alert_days"]
	cutoff = add_days(today(), -int(days))

	rows = frappe.get_all(
		"LMS Borrower Compliance",
		filters={"kyc_status": ("in", ["Pending", "In Review"])},
		fields=["name", "customer", "kyc_status", "modified", "national_id_number"],
		order_by="modified asc",
		limit_page_length=50,
	)
	out = []
	for row in rows:
		mod = getdate(row.modified) if row.modified else getdate(today())
		if mod > getdate(cutoff):
			continue
		customer_name = frappe.db.get_value("Customer", row.customer, "customer_name") or row.customer
		out.append(
			{
				"compliance": row.name,
				"customer": row.customer,
				"customer_name": customer_name,
				"kyc_status": row.kyc_status,
				"days_pending": (getdate(today()) - mod).days,
			}
		)
	return out


def _dues_today_count() -> int:
	schedule_parents = frappe.get_all("Loan Repayment Schedule", filters={"docstatus": 1}, pluck="name")
	if not schedule_parents:
		return 0
	return frappe.db.count(
		"Repayment Schedule",
		{
			"parent": ("in", schedule_parents),
			"parenttype": "Loan Repayment Schedule",
			"payment_date": today(),
		},
	)


def _new_arrears_count() -> int:
	"""Loans that crossed into DPD > 0 since yesterday (approximation via custom field)."""
	yesterday_dpd_threshold = 0
	loans = frappe.get_all(
		"Loan",
		filters={
			"docstatus": 1,
			"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
			"custom_days_past_due": (">", yesterday_dpd_threshold),
		},
		pluck="name",
	)
	return len(loans)


def build_morning_digest_context(company=None) -> dict:
	"""Aggregate KPIs and chart HTML for the daily digest email."""
	metrics = _portfolio_metrics(company)
	kpis = metrics["kpis"]
	risk_rows = rows_from_risk_buckets(metrics["risk_buckets"])
	collections_rows = _collections_trend(company=company)

	for row in risk_rows:
		row["value_display"] = frappe.format_value(row["value"], {"fieldtype": "Currency"})
	for row in collections_rows:
		row["value_display"] = frappe.format_value(row["value"], {"fieldtype": "Currency"})

	open_incidents = frappe.db.count(
		"LMS Incident Log", {"status": ("in", ["Open", "Investigating"])}
	)
	kyc_pending = get_kyc_pending_rows()

	return {
		"report_date": str(getdate(today())),
		"portfolio_outstanding": kpis.get("portfolio_outstanding"),
		"par30_outstanding": kpis.get("par30_outstanding"),
		"par90_outstanding": kpis.get("par90_outstanding"),
		"active_loans": kpis.get("active_loans"),
		"npa_count": kpis.get("npa_count"),
		"dues_today": _dues_today_count(),
		"new_arrears": _new_arrears_count(),
		"open_incidents": open_incidents,
		"kyc_pending_count": len(kyc_pending),
		"kyc_pending_list": kyc_pending,
		"risk_chart_html": render_email_bar_chart(risk_rows, title="Risk composition (outstanding)"),
		"collections_chart_html": render_email_bar_chart(
			collections_rows, title="Collections trend (last 6 months)"
		),
		"portfolio_outstanding_fmt": frappe.format_value(
			kpis.get("portfolio_outstanding"), {"fieldtype": "Currency"}
		),
		"par30_fmt": frappe.format_value(kpis.get("par30_outstanding"), {"fieldtype": "Currency"}),
		"par90_fmt": frappe.format_value(kpis.get("par90_outstanding"), {"fieldtype": "Currency"}),
	}
