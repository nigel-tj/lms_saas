"""Best-effort: link demo Branch Manager to an Employee for HR zero-state exit.

bench --site lms.localhost execute lms_saas.setup.seed_r9_hr.run
"""

from __future__ import annotations

import frappe


def run():
	user = "demo.lms.branch@example.com"
	if not frappe.db.exists("User", user):
		return {"ok": False, "reason": "demo manager missing"}

	if not frappe.db.table_exists("Employee"):
		return {"ok": False, "reason": "Employee table missing"}

	existing = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if existing:
		return {"ok": True, "employee": existing, "created": False}

	meta = frappe.get_meta("Employee")
	doc = frappe.new_doc("Employee")
	if meta.has_field("first_name"):
		doc.first_name = "Demo"
	if meta.has_field("last_name"):
		doc.last_name = "Branch Manager"
	if meta.has_field("employee_name"):
		doc.employee_name = "Demo Branch Manager"
	if meta.has_field("user_id"):
		doc.user_id = user
	if meta.has_field("status"):
		doc.status = "Active"
	if meta.has_field("company"):
		company = frappe.db.get_single_value("Global Defaults", "default_company")
		if company:
			doc.company = company
	# Branch / cost center if present
	branch = frappe.db.get_value("User Permission", {"user": user, "allow": "Cost Center"}, "for_value")
	for field in ("branch", "cost_center", "custom_lms_branch"):
		if branch and meta.has_field(field):
			setattr(doc, field, branch)
			break
	if meta.has_field("date_of_joining"):
		from frappe.utils import today
		doc.date_of_joining = today()
	if meta.has_field("gender"):
		opts = [o for o in (meta.get_field("gender").options or "").split("\n") if o.strip()]
		if opts:
			doc.gender = opts[0]
	doc.flags.ignore_permissions = True
	try:
		doc.insert()
		frappe.db.commit()
		return {"ok": True, "employee": doc.name, "created": True}
	except Exception as e:
		return {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
