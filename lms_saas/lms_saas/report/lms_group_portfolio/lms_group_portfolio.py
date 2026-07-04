import frappe


def execute(filters=None):
	filters = filters or {}
	company = filters.get("company")
	rows = []
	groups = frappe.get_all(
		"LMS Lending Group",
		filters={"company": company} if company else {},
		fields=["name", "group_name", "branch", "status"],
	)
	for group in groups:
		members = frappe.get_all(
			"LMS Group Member",
			filters={"parent": group.name, "parenttype": "LMS Lending Group"},
			pluck="customer",
		)
		outstanding = 0.0
		active_loans = 0
		if members:
			loans = frappe.get_all(
				"Loan",
				filters={
					"applicant": ("in", members),
					"docstatus": 1,
					"status": ("in", ["Disbursed", "Active", "Partially Disbursed"]),
				},
				fields=["name", "total_payment", "total_amount_paid"],
			)
			active_loans = len(loans)
			for loan in loans:
				outstanding += (loan.total_payment or 0) - (loan.total_amount_paid or 0)

		rows.append(
			{
				"group": group.name,
				"group_name": group.group_name,
				"branch": group.branch,
				"members": len(members),
				"active_loans": active_loans,
				"outstanding": outstanding,
				"status": group.status,
			}
		)

	columns = [
		{"label": "Group", "fieldname": "group_name", "fieldtype": "Data", "width": 180},
		{"label": "Branch", "fieldname": "branch", "fieldtype": "Link", "options": "Cost Center", "width": 120},
		{"label": "Members", "fieldname": "members", "fieldtype": "Int", "width": 80},
		{"label": "Active Loans", "fieldname": "active_loans", "fieldtype": "Int", "width": 100},
		{"label": "Outstanding", "fieldname": "outstanding", "fieldtype": "Currency", "width": 120},
		{"label": "Status", "fieldname": "status", "fieldtype": "Data", "width": 90},
	]
	return columns, rows
