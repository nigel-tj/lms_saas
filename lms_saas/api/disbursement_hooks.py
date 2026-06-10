"""Loan disbursement hooks."""

import frappe


def notify_disbursed(doc, method=None):
	try:
		from lms_saas.api.webhooks import dispatch_webhook_event

		dispatch_webhook_event(
			"loan.disbursed",
			{
				"disbursement": doc.name,
				"loan": doc.against_loan,
				"amount": doc.disbursed_amount,
				"company": doc.company,
			},
		)
	except Exception:
		pass
