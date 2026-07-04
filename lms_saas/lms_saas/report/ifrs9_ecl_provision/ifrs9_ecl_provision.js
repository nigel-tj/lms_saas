frappe.query_reports["IFRS9 ECL Provision"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "branch",
			label: __("Branch"),
			fieldtype: "Link",
			options: "Cost Center",
		},
		{
			fieldname: "loan_officer",
			label: __("Loan Officer"),
			fieldtype: "Link",
			options: "Employee",
		},
	],
};
