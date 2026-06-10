"""Debug helper: bench execute lms_saas.setup.check_notification_log.run"""

import frappe


def run():
	print("doctype_exists", frappe.db.exists("DocType", "LMS Notification Log"))
	print("table_exists", frappe.db.table_exists("LMS Notification Log"))
	print("incident_table", frappe.db.table_exists("tabLMS Incident Log"))
	print("audit_table", frappe.db.table_exists("tabLMS Audit Event"))
	if frappe.db.exists("DocType", "LMS Notification Log"):
		meta = frappe.get_meta("LMS Notification Log")
		print("istable", meta.istable, "issingle", meta.issingle)
	for role in ("LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector"):
		custom = frappe.db.get_value(
			"Custom DocPerm", {"parent": "LMS Notification Log", "role": role}, ["read", "write"], as_dict=True
		)
		standard = frappe.db.get_value(
			"DocPerm", {"parent": "LMS Notification Log", "role": role}, ["read", "write"], as_dict=True
		)
		print(role, "custom", custom, "standard", standard)
