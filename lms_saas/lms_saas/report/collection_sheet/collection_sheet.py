import frappe
from frappe.utils import add_days, getdate, today


def execute(filters=None):
	filters = filters or {}
	company = filters.get("company")
	days_ahead = int(filters.get("days_ahead") or 7)
	end_date = add_days(today(), days_ahead)

	schedule_parents = frappe.get_all("Loan Repayment Schedule", filters={"docstatus": 1}, pluck="name")
	if not schedule_parents:
		return _columns(), []

	# R58: window starts in the past so unpaid installments before today are
	# surfaced as overdue, instead of vanishing the day after their date.
	rows = frappe.get_all(
		"Repayment Schedule",
		filters={
			"parent": ("in", schedule_parents),
			"parenttype": "Loan Repayment Schedule",
			"payment_date": ("<", end_date),
		},
		fields=["parent", "payment_date", "total_payment", "principal_amount", "interest_amount"],
		order_by="payment_date asc",
	)

	# Batch fetch: map schedule parent → loan (single query)
	parent_to_loan = {
		r["name"]: r["loan"]
		for r in frappe.get_all(
			"Loan Repayment Schedule",
			filters={"name": ("in", schedule_parents)},
			fields=["name", "loan"],
		)
	}

	# Batch fetch: all loan details in one query
	loan_names = list(set(parent_to_loan.values()))
	loan_map = {}
	if loan_names:
		for loan in frappe.get_all(
			"Loan",
			filters={"name": ("in", loan_names)},
			fields=[
				"name",
				"applicant",
				"applicant_type",
				"company",
				"custom_lms_branch",
				"total_payment",
				"total_amount_paid",
			],
		):
			loan_map[loan.name] = loan

	# Batch fetch: customer contacts
	customer_names = [l.applicant for l in loan_map.values() if l.applicant_type == "Customer"]
	customer_mobiles = {}
	if customer_names:
		for c in frappe.get_all(
			"Customer", filters={"name": ("in", customer_names)}, fields=["name", "mobile_no"]
		):
			customer_mobiles[c.name] = c.mobile_no

	columns = _columns()
	data = []

	for row in rows:
		loan_name = parent_to_loan.get(row.parent)
		if not loan_name:
			continue

		loan = loan_map.get(loan_name)
		if not loan:
			continue
		if company and loan.company != company:
			continue

		amount = row.total_payment or (row.principal_amount or 0) + (row.interest_amount or 0)

		# R58 bucket: overdue = payment date before today AND not yet covered by
		# repayments; upcoming = today or later, unpaid. An installment whose
		# amount has already been collected (the loan's paid total has moved
		# past this row's cumulative position) is excluded entirely — the
		# collector must not be sent to a borrower who already paid.
		is_overdue = getdate(row.payment_date) < getdate(today())
		if not is_overdue and _installment_covered(loan, rows, row):
			continue

		mobile = customer_mobiles.get(loan.applicant, "") if loan.applicant_type == "Customer" else ""

		data.append(
			{
				"loan": loan_name,
				"borrower": loan.applicant,
				"branch": loan.custom_lms_branch,
				"due_date": row.payment_date,
				"amount": amount,
				"mobile": mobile,
				"bucket": "overdue" if is_overdue else "upcoming",
			}
		)

	# R58 ordering: most-overdue first, then upcoming by payment date.
	data.sort(key=lambda r: (0 if r["bucket"] == "overdue" else 1, r["due_date"]))

	return columns, data


def _installment_covered(loan, all_schedule_rows, current_row):
	"""True when the loan's repayments have already covered this installment.

	Paid-progress check: cumulative amount of THIS SCHEDULE's installments up
	to and including the current row vs the loan's total_amount_paid. When
	paid >= cumulative, the collector no longer needs this stop. Uses the
	batch-loaded loan fields — no per-row queries.
	"""
	total_paid = loan.total_amount_paid or 0
	if not total_paid:
		return False
	cumulative = 0.0
	for r in all_schedule_rows:
		# Cumulative position is per-schedule: other loans' installments
		# must not pollute the total this row is compared against.
		if r.parent != current_row.parent:
			continue
		amt = r.total_payment or (r.principal_amount or 0) + (r.interest_amount or 0)
		cumulative += amt or 0
		if r.payment_date == current_row.payment_date:
			# reached the current row: covered when paid has moved past it
			return total_paid >= cumulative - 0.005
	return False


def _columns():
	return [
		{"label": "Due Date", "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": "Loan", "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 130},
		{"label": "Borrower", "fieldname": "borrower", "fieldtype": "Data", "width": 160},
		{"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Cost Center", "width": 120},
		{"label": "Amount", "fieldname": "amount", "fieldtype": "Currency", "width": 100},
		{"label": "Mobile", "fieldname": "mobile", "fieldtype": "Data", "width": 120},
		{"label": "Bucket", "fieldname": "bucket", "fieldtype": "Data", "width": 90},
	]


def _contact_for_applicant(applicant_type, applicant):
	if applicant_type == "Customer":
		return frappe.db.get_value("Customer", applicant, "mobile_no")
	if applicant_type == "Employee":
		return frappe.db.get_value("Employee", applicant, "cell_number")
	return None
