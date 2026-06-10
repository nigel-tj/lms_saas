frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["LMS Portfolio"] = {
	method: "lms_saas.api.dashboard.get_chart_data",
	filters: [
		{
			fieldname: "metric",
			label: __("Metric"),
			fieldtype: "Select",
			options: ["risk_composition", "collections_trend", "branch_concentration"].join("\n"),
			default: "risk_composition",
			reqd: 1,
		},
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
	],
};
