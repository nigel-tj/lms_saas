"""Collections escalation, notification idempotency, and consent gates."""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_days, flt, getdate, now_datetime, today

DEFAULT_DPD_MILESTONES = [1, 7, 30]
DEFAULT_REMIND_DAYS_BEFORE = 3
DEFAULT_KYC_PENDING_ALERT_DAYS = 3


def count_failed_notifications(days: int = 7) -> int:
	"""Failed SMS/email sends in the period (for weekly KPI / digest)."""
	from frappe.utils import add_days

	since = add_days(today(), -int(days))
	return frappe.db.count(
		"LMS Notification Log",
		{"status": "Failed", "notification_date": (">=", since)},
	)


def get_collections_config():
	"""Read automation flags from site_config (all OFF by default)."""
	raw_milestones = frappe.conf.get("lms_collections_dpd_milestones")
	if isinstance(raw_milestones, str):
		try:
			raw_milestones = json.loads(raw_milestones)
		except json.JSONDecodeError:
			raw_milestones = None
	if not raw_milestones:
		raw_milestones = DEFAULT_DPD_MILESTONES

	milestones = sorted({int(m) for m in raw_milestones if int(m) > 0})

	return {
		"escalation_enabled": bool(frappe.conf.get("lms_collections_escalation_enabled", False)),
		"digest_enabled": bool(frappe.conf.get("lms_digest_enabled", False)),
		"weekly_kpi_enabled": bool(frappe.conf.get("lms_weekly_kpi_enabled", False)),
		"dpd_milestones": milestones,
		"remind_days_before": int(frappe.conf.get("lms_collections_remind_days_before", DEFAULT_REMIND_DAYS_BEFORE)),
		"kyc_pending_alert_days": int(
			frappe.conf.get("lms_kyc_pending_alert_days", DEFAULT_KYC_PENDING_ALERT_DAYS)
		),
		"require_consent": bool(frappe.conf.get("lms_require_consent", False)),
	}


def borrower_has_consent(customer: str) -> bool:
	if not customer:
		return False
	return bool(frappe.db.get_value("LMS Borrower Compliance", {"customer": customer}, "consent_given"))


def should_skip_for_consent(applicant_type: str, applicant: str, config: dict | None = None) -> bool:
	config = config or get_collections_config()
	if not config.get("require_consent"):
		return False
	if applicant_type != "Customer":
		return False
	return not borrower_has_consent(applicant)


def should_send_notification(
	loan: str,
	reminder_type: str,
	notification_date,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
) -> bool:
	"""Idempotency: one send per (loan, reference, reminder_type, date)."""
	if not loan or not reminder_type:
		return False
	notif_date = getdate(notification_date or today())
	filters = {
		"loan": loan,
		"reminder_type": reminder_type,
		"notification_date": notif_date,
	}
	if reference_doctype:
		filters["reference_doctype"] = reference_doctype
	else:
		filters["reference_doctype"] = ("is", "not set")
	if reference_name:
		filters["reference_name"] = reference_name
	else:
		filters["reference_name"] = ("is", "not set")

	return not frappe.db.exists("LMS Notification Log", filters)


def log_notification(
	loan: str,
	reminder_type: str,
	channel: str,
	status: str,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	recipient: str | None = None,
	message_preview: str | None = None,
	notification_date=None,
) -> str | None:
	"""Persist notification outcome for audit and idempotency."""
	try:
		doc = frappe.get_doc(
			{
				"doctype": "LMS Notification Log",
				"loan": loan,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"reminder_type": reminder_type,
				"notification_date": getdate(notification_date or today()),
				"channel": channel,
				"status": status,
				"recipient": (recipient or "")[:140],
				"message_preview": (message_preview or "")[:500],
				"sent_on": now_datetime(),
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception:  # noqa: BLE001
		frappe.log_error(title="LMS notification log failed", message=frappe.get_traceback())
		return None


def escalation_message(reminder_type: str, loan_name: str, *, dpd: int = 0, due_date=None) -> str:
	"""Escalating tone for SMS/email copy."""
	due_str = str(due_date) if due_date else ""
	if reminder_type.startswith("upcoming"):
		return (
			f"Reminder: Your installment for Loan {loan_name} is due on {due_str}. "
			"Please plan your payment to stay current."
		)
	if reminder_type == "due_today":
		return (
			f"Payment due today for Loan {loan_name}. "
			"Please pay today to avoid late fees and protect your credit standing."
		)
	if reminder_type.startswith("dpd_"):
		if dpd >= 30:
			return (
				f"Urgent: Loan {loan_name} is {dpd} days past due. "
				"Immediate payment is required to avoid further collection action."
			)
		if dpd >= 7:
			return (
				f"Important: Loan {loan_name} is {dpd} days past due. "
				"Contact us today to arrange payment and avoid escalation."
			)
		return (
			f"Notice: Loan {loan_name} is {dpd} day(s) past due. "
			"Please settle the overdue amount as soon as possible."
		)
	return f"Loan {loan_name}: payment reminder."


def get_applicant_contact(applicant_type: str, applicant: str) -> dict:
	mobile = None
	email = None
	customer_name = applicant
	if applicant_type == "Customer":
		row = frappe.db.get_value(
			"Customer", applicant, ["mobile_no", "email_id", "customer_name"], as_dict=True
		)
		if row:
			mobile = row.mobile_no
			email = row.email_id
			customer_name = row.customer_name or applicant
	elif applicant_type == "Employee":
		mobile = frappe.db.get_value("Employee", applicant, "cell_number")
	return {"mobile": mobile, "email": email, "customer_name": customer_name}


def send_loan_reminder(
	loan_name: str,
	reminder_type: str,
	message: str,
	*,
	reference_doctype: str | None = None,
	reference_name: str | None = None,
	notification_date=None,
	config: dict | None = None,
) -> None:
	"""Send SMS + email for one loan reminder with idempotency and consent."""
	config = config or get_collections_config()
	notif_date = getdate(notification_date or today())

	if not should_send_notification(
		loan_name,
		reminder_type,
		notif_date,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
	):
		return

	loan = frappe.db.get_value(
		"Loan", loan_name, ["applicant_type", "applicant"], as_dict=True
	)
	if not loan:
		return

	if should_skip_for_consent(loan.applicant_type, loan.applicant, config):
		log_notification(
			loan_name,
			reminder_type,
			"SMS",
			"Skipped",
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			message_preview="Consent not recorded",
			notification_date=notif_date,
		)
		log_notification(
			loan_name,
			reminder_type,
			"Email",
			"Skipped",
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			message_preview="Consent not recorded",
			notification_date=notif_date,
		)
		return

	contact = get_applicant_contact(loan.applicant_type, loan.applicant)
	sms_status = "Skipped"
	if contact.get("mobile"):
		from lms_saas.api.notifications import dispatch_sms_gateway

		ok = dispatch_sms_gateway(contact["mobile"], message)
		sms_status = "Sent" if ok else "Failed"
		log_notification(
			loan_name,
			reminder_type,
			"SMS",
			sms_status,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			recipient=contact["mobile"],
			message_preview=message,
			notification_date=notif_date,
		)
	else:
		log_notification(
			loan_name,
			reminder_type,
			"SMS",
			"Skipped",
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			message_preview="No mobile number",
			notification_date=notif_date,
		)

	if loan.applicant_type == "Customer" and contact.get("email"):
		from lms_saas.utils.email import send_branded_email

		try:
			send_branded_email(
				recipients=[contact["email"]],
				subject=_reminder_email_subject(reminder_type, loan_name),
				body_key="payment_reminder",
				context={
					"customer_name": contact.get("customer_name"),
					"loan_name": loan_name,
					"message": message,
				},
				delayed=True,
				reference_doctype="Loan",
				reference_name=loan_name,
			)
			email_status = "Sent"
		except Exception:  # noqa: BLE001
			frappe.log_error(title="LMS collection email failed", message=frappe.get_traceback())
			email_status = "Failed"
		log_notification(
			loan_name,
			reminder_type,
			"Email",
			email_status,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			recipient=contact["email"],
			message_preview=message,
			notification_date=notif_date,
		)
	else:
		log_notification(
			loan_name,
			reminder_type,
			"Email",
			"Skipped",
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			message_preview="No email address",
			notification_date=notif_date,
		)


def _reminder_email_subject(reminder_type: str, loan_name: str) -> str:
	if reminder_type.startswith("dpd_"):
		return f"Overdue payment notice — {loan_name}"
	if reminder_type == "due_today":
		return f"Payment due today — {loan_name}"
	return f"Upcoming loan payment reminder — {loan_name}"


def create_collector_todo(loan_name: str, dpd: int, config: dict | None = None) -> None:
	"""Desk ToDo for collectors when DPD >= 7."""
	config = config or get_collections_config()
	reminder_type = f"collector_todo_dpd_{dpd}"
	notif_date = getdate(today())
	ref_dt = "Loan"
	if not should_send_notification(loan_name, reminder_type, notif_date, reference_doctype=ref_dt, reference_name=loan_name):
		return

	loan = frappe.db.get_value(
		"Loan",
		loan_name,
		["applicant", "applicant_type", "custom_loan_officer", "company"],
		as_dict=True,
	)
	if not loan:
		return

	if should_skip_for_consent(loan.applicant_type, loan.applicant, config):
		log_notification(
			loan_name,
			reminder_type,
			"ToDo",
			"Skipped",
			reference_doctype=ref_dt,
			reference_name=loan_name,
			message_preview="Consent not recorded",
			notification_date=notif_date,
		)
		return

	assignees = _collector_assignees(loan.custom_loan_officer)
	if not assignees:
		log_notification(
			loan_name,
			reminder_type,
			"ToDo",
			"Skipped",
			reference_doctype=ref_dt,
			reference_name=loan_name,
			message_preview="No collector assignee",
			notification_date=notif_date,
		)
		return

	description = (
		f"Collections follow-up: Loan {loan_name} is {dpd} days past due. "
		f"Borrower: {loan.applicant}. Contact borrower and log outcome."
	)
	try:
		todo = frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": description,
				"reference_type": "Loan",
				"reference_name": loan_name,
				"priority": "High" if dpd >= 30 else "Medium",
				"allocated_to": assignees[0],
				"assigned_by": "Administrator",
			}
		)
		todo.insert(ignore_permissions=True)
		status = "Sent"
	except Exception:  # noqa: BLE001
		frappe.log_error(title="LMS collector ToDo failed", message=frappe.get_traceback())
		status = "Failed"

	log_notification(
		loan_name,
		reminder_type,
		"ToDo",
		status,
		reference_doctype=ref_dt,
		reference_name=loan_name,
		recipient=assignees[0],
		message_preview=description[:500],
		notification_date=notif_date,
	)


def _collector_assignees(loan_officer: str | None) -> list[str]:
	if loan_officer:
		user = frappe.db.get_value("Employee", loan_officer, "user_id")
		if user and user != "Guest":
			return [user]

	users = set()
	for role in ("LMS Collector", "LMS Branch Manager"):
		for row in frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"):
			if row not in ("Administrator", "Guest"):
				users.add(row)
	return sorted(users)[:5]


def run_collections_escalation() -> None:
	"""Daily collections job: T-N, due today, DPD milestones, collector ToDos."""
	config = get_collections_config()
	if not config["escalation_enabled"]:
		return

	posting_date = getdate(today())
	_send_upcoming_reminders(config, posting_date)
	_send_due_today_reminders(config, posting_date)
	_send_dpd_milestone_reminders(config, posting_date)


def _schedule_parents():
	return frappe.get_all("Loan Repayment Schedule", filters={"docstatus": 1}, pluck="name")


def _schedule_rows_for_date(payment_date, schedule_parents=None):
	parents = schedule_parents or _schedule_parents()
	if not parents:
		return []
	return frappe.get_all(
		"Repayment Schedule",
		filters={
			"parent": ("in", parents),
			"parenttype": "Loan Repayment Schedule",
			"payment_date": payment_date,
		},
		fields=["parent", "name", "payment_date"],
	)


def _send_upcoming_reminders(config, posting_date):
	target = add_days(posting_date, config["remind_days_before"])
	for row in _schedule_rows_for_date(target):
		loan_name = frappe.db.get_value("Loan Repayment Schedule", row.parent, "loan")
		if not loan_name:
			continue
		reminder_type = f"upcoming_t{config['remind_days_before']}"
		msg = escalation_message(reminder_type, loan_name, due_date=target)
		send_loan_reminder(
			loan_name,
			reminder_type,
			msg,
			reference_doctype="Repayment Schedule",
			reference_name=row.name,
			notification_date=posting_date,
			config=config,
		)


def _send_due_today_reminders(config, posting_date):
	for row in _schedule_rows_for_date(posting_date):
		loan_name = frappe.db.get_value("Loan Repayment Schedule", row.parent, "loan")
		if not loan_name:
			continue
		msg = escalation_message("due_today", loan_name, due_date=posting_date)
		send_loan_reminder(
			loan_name,
			"due_today",
			msg,
			reference_doctype="Repayment Schedule",
			reference_name=row.name,
			notification_date=posting_date,
			config=config,
		)


def _send_dpd_milestone_reminders(config, posting_date):
	loans = frappe.get_all(
		"Loan",
		filters={"docstatus": 1, "status": ("in", ["Disbursed", "Active", "Partially Disbursed"])},
		fields=["name", "custom_days_past_due", "days_past_due"],
	)
	milestones = set(config["dpd_milestones"])

	for loan in loans:
		dpd = int(flt(loan.custom_days_past_due or loan.days_past_due or 0))
		if dpd <= 0:
			continue
		if dpd not in milestones:
			continue

		reminder_type = f"dpd_{dpd}"
		msg = escalation_message(reminder_type, loan.name, dpd=dpd)
		send_loan_reminder(
			loan.name,
			reminder_type,
			msg,
			reference_doctype="Loan",
			reference_name=loan.name,
			notification_date=posting_date,
			config=config,
		)

		if dpd >= 7:
			create_collector_todo(loan.name, dpd, config=config)
