"""Script report wrapping RBZ weekly sandbox KPI data with 4-week trend chart."""

import frappe
from frappe.utils import add_days, flt, getdate, today

from lms_saas.api.compliance import get_sandbox_report


def execute(filters=None):
	filters = filters or {}
	days = int(filters.get("days") or 7)
	report = get_sandbox_report(days=days)

	columns = [
		{"label": "Metric", "fieldname": "metric", "fieldtype": "Data", "width": 220},
		{"label": "Value", "fieldname": "value", "fieldtype": "Data", "width": 200},
	]

	data = [
		{"metric": "Volunteer customers", "value": str(report.get("volunteer_customers", 0))},
		{
			"metric": "Disbursements (count / value)",
			"value": f"{report['transactions']['disbursements_count']} / "
			f"{frappe.format_value(report['transactions']['disbursements_value'], {'fieldtype': 'Currency'})}",
		},
		{
			"metric": "Repayments (count / value)",
			"value": f"{report['transactions']['repayments_count']} / "
			f"{frappe.format_value(report['transactions']['repayments_value'], {'fieldtype': 'Currency'})}",
		},
		{"metric": "Open incidents", "value": str(report.get("incidents_open", 0))},
		{"metric": "Complaints (period)", "value": str(report.get("complaints", 0))},
		{"metric": "Audit events (period)", "value": str(report.get("audit_events", 0))},
	]

	trend = _four_week_transaction_trend()
	chart = {
		"data": {
			"labels": [row["label"] for row in trend],
			"datasets": [
				{"name": "Disbursements", "values": [row["disbursements"] for row in trend]},
				{"name": "Repayments", "values": [row["repayments"] for row in trend]},
			],
		},
		"type": "line",
	}

	report_summary = [
		{
			"label": "Disbursements",
			"value": report["transactions"]["disbursements_value"],
			"datatype": "Currency",
		},
		{"label": "Repayments", "value": report["transactions"]["repayments_value"], "datatype": "Currency"},
		{"label": "Complaints", "value": report.get("complaints", 0), "datatype": "Int"},
	]

	return columns, data, None, chart, report_summary


def _four_week_transaction_trend(weeks=4):
	rows = []
	for offset in range(weeks - 1, -1, -1):
		end = getdate(add_days(today(), -7 * offset))
		start = getdate(add_days(end, -6))
		disbursements = frappe.db.sql(
			"""
			select coalesce(sum(disbursed_amount), 0)
			from `tabLoan Disbursement`
			where docstatus = 1 and posting_date between %s and %s
			""",
			(start, end),
		)[0][0]
		repayments = frappe.db.sql(
			"""
			select coalesce(sum(amount_paid), 0)
			from `tabLoan Repayment`
			where docstatus = 1 and posting_date between %s and %s
			""",
			(start, end),
		)[0][0]
		rows.append(
			{
				"label": end.strftime("%d %b"),
				"disbursements": flt(disbursements),
				"repayments": flt(repayments),
			}
		)
	return rows
