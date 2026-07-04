import json

import frappe
from frappe.utils import add_days, date_diff, flt, getdate, today

from lms_saas.utils.calculations import asset_classification

DPD_COMMIT_BATCH = 200


def run_daily_loan_cron():
	"""
	Nightly loan portfolio: DPD mirror, collections escalation, morning digest.
	Collections and digest are config-gated (OFF by default).
	"""
	evaluate_days_past_due()

	from lms_saas.api.collections import get_collections_config, run_collections_escalation

	config = get_collections_config()
	if config["escalation_enabled"]:
		run_collections_escalation()
	else:
		send_upcoming_payment_reminders()

	if config["digest_enabled"]:
		send_morning_digest()

	from lms_saas.api.payments.service import reconcile_pending_payments

	reconcile_pending_payments()


def evaluate_days_past_due():
	"""Mirror loan delinquency into LMS reporting fields.

	Native DPD/NPA classification (including suspense-ledger GL postings) is
	owned by the lending app's scheduled ``process_loan_classification`` job.
	This task only mirrors the resulting delinquency onto the ``custom_*``
	fields used by LMS dashboards and reports. DPD is derived defensively from
	the repayment schedule so this job never depends on GL account
	configuration and cannot break the nightly run.
	"""
	posting_date = getdate(today())
	active_loans = frappe.get_all(
		"Loan",
		filters={"status": "Disbursed", "docstatus": 1},
		fields=["name", "days_past_due"],
	)

	for index, loan in enumerate(active_loans, start=1):
		try:
			overdue_dates = _get_overdue_schedule_dates(loan.name)
			dpd = loan.days_past_due or 0

			if overdue_dates:
				oldest_due = min(overdue_dates)
				dpd = max(dpd, date_diff(posting_date, oldest_due))

			classification = asset_classification(dpd)

			frappe.db.set_value(
				"Loan",
				loan.name,
				{
					"custom_days_past_due": dpd,
					"custom_asset_classification": classification,
				},
				update_modified=False,
			)
		except Exception:  # noqa: BLE001 - one bad loan must not abort the nightly run
			frappe.log_error(
				title=f"LMS DPD mirror failed: {loan.name}",
				message=frappe.get_traceback(),
			)

		if index % DPD_COMMIT_BATCH == 0:
			frappe.db.commit()

	frappe.db.commit()


def _get_overdue_schedule_dates(loan_name):
	schedule_parents = frappe.get_all(
		"Loan Repayment Schedule",
		filters={"loan": loan_name, "docstatus": 1},
		pluck="name",
	)
	if not schedule_parents:
		return []

	return frappe.get_all(
		"Repayment Schedule",
		filters={
			"parent": ("in", schedule_parents),
			"parenttype": "Loan Repayment Schedule",
			"payment_date": ("<", today()),
		},
		pluck="payment_date",
	)


def send_upcoming_payment_reminders():
	"""Legacy T-3 path when collections escalation is disabled."""
	from lms_saas.api.collections import get_collections_config

	config = get_collections_config()
	days_before = config["remind_days_before"]
	target_reminder_date = add_days(today(), days_before)
	schedule_parents = frappe.get_all("Loan Repayment Schedule", filters={"docstatus": 1}, pluck="name")

	if not schedule_parents:
		return

	upcoming_rows = frappe.get_all(
		"Repayment Schedule",
		filters={
			"parent": ("in", schedule_parents),
			"parenttype": "Loan Repayment Schedule",
			"payment_date": target_reminder_date,
		},
		fields=["parent", "name"],
	)

	for schedule in upcoming_rows:
		loan_name = frappe.db.get_value("Loan Repayment Schedule", schedule.parent, "loan")
		if not loan_name:
			continue

		from lms_saas.api.collections import escalation_message, send_loan_reminder

		msg = escalation_message(
			f"upcoming_t{days_before}", loan_name, due_date=target_reminder_date
		)
		send_loan_reminder(
			loan_name,
			f"upcoming_t{days_before}",
			msg,
			reference_doctype="Repayment Schedule",
			reference_name=schedule.name,
			config=config,
		)


def send_morning_digest():
	"""Daily branch digest email (config: lms_digest_enabled)."""
	from lms_saas.api.collections import get_collections_config
	from lms_saas.api.digests import build_morning_digest_context, get_digest_recipients
	from lms_saas.utils.email import send_branded_email

	config = get_collections_config()
	if not config["digest_enabled"]:
		return

	recipients = get_digest_recipients()
	if not recipients:
		frappe.log_error(
			title="LMS morning digest skipped",
			message="No recipients (set lms_digest_recipients or assign LMS Branch Manager users with email).",
		)
		return

	ctx = build_morning_digest_context()
	send_branded_email(
		recipients=recipients,
		subject=f"LMS morning digest — {ctx['report_date']}",
		body_key="morning_digest",
		context=ctx,
		delayed=True,
	)


def send_weekly_sandbox_kpi_pack():
	"""Weekly RBZ sandbox KPI email with JSON attachment (config: lms_weekly_kpi_enabled)."""
	from lms_saas.api.collections import get_collections_config

	config = get_collections_config()
	if not config["weekly_kpi_enabled"]:
		return

	raw_recipients = (frappe.conf.get("lms_compliance_report_recipients") or "").strip()
	if not raw_recipients:
		frappe.log_error(
			title="LMS weekly KPI skipped",
			message="Set lms_compliance_report_recipients in site_config (comma-separated emails).",
		)
		return

	from lms_saas.api.compliance import get_sandbox_report
	from lms_saas.utils.charts import render_email_bar_chart
	from lms_saas.utils.email import send_branded_email

	from lms_saas.api.collections import count_failed_notifications

	report = get_sandbox_report(days=7)
	trend_rows = _weekly_kpi_trend_rows()
	report["trend_weeks"] = trend_rows
	notifications_failed = count_failed_notifications(days=7)

	ctx = {
		"report": report,
		"period_days": report.get("period_days"),
		"since": report.get("since"),
		"volunteer_customers": report.get("volunteer_customers"),
		"disbursements_count": report["transactions"]["disbursements_count"],
		"disbursements_value": frappe.format_value(
			report["transactions"]["disbursements_value"], {"fieldtype": "Currency"}
		),
		"repayments_count": report["transactions"]["repayments_count"],
		"repayments_value": frappe.format_value(
			report["transactions"]["repayments_value"], {"fieldtype": "Currency"}
		),
		"incidents_open": report.get("incidents_open"),
		"complaints": report.get("complaints"),
		"audit_events": report.get("audit_events"),
		"notifications_failed": notifications_failed,
		"trend_chart_html": render_email_bar_chart(
			[
				{
					"label": row["label"],
					"value": row["disbursements_value"],
					"value_display": frappe.format_value(
						row["disbursements_value"], {"fieldtype": "Currency"}
					),
				}
				for row in trend_rows
			],
			title="Disbursement value — 4-week trend",
		),
		"repayment_trend_chart_html": render_email_bar_chart(
			[
				{
					"label": row["label"],
					"value": row["repayments_value"],
					"value_display": frappe.format_value(
						row["repayments_value"], {"fieldtype": "Currency"}
					),
				}
				for row in trend_rows
			],
			title="Repayment value — 4-week trend",
			bar_color="#22c55e",
		),
		"incident_chart_html": render_email_bar_chart(
			[
				{"label": "Open incidents", "value": report.get("incidents_open") or 0},
				{"label": "Complaints (period)", "value": report.get("complaints") or 0},
				{"label": "Failed notifications", "value": notifications_failed},
			],
			title="Operational health (period)",
			bar_color="#dc2626",
		),
	}

	recipients = [e.strip() for e in raw_recipients.split(",") if e.strip()]
	attachment = {
		"fname": f"lms_sandbox_kpi_{today()}.json",
		"fcontent": json.dumps(report, indent=2, default=str),
	}

	send_branded_email(
		recipients=recipients,
		subject=f"LMS sandbox weekly KPI — week ending {today()}",
		body_key="kpi_pack",
		context=ctx,
		delayed=True,
		attachments=[attachment],
	)


def _weekly_kpi_trend_rows(weeks=4):
	"""Weekly disbursement and repayment totals for chart trends."""
	rows = []
	for offset in range(weeks - 1, -1, -1):
		end = getdate(add_days(today(), -7 * offset))
		start = getdate(add_days(end, -6))
		disbursements_value = frappe.db.sql(
			"""
			select coalesce(sum(disbursed_amount), 0)
			from `tabLoan Disbursement`
			where docstatus = 1 and posting_date between %s and %s
			""",
			(start, end),
		)[0][0]
		repayments_value = frappe.db.sql(
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
				"disbursements_value": flt(disbursements_value),
				"repayments_value": flt(repayments_value),
				"start": str(start),
				"end": str(end),
			}
		)
	return rows
