"""Bootstrap the demo Branch Manager for end-to-end smoke testing.

- Sets `Employee.custom_lms_persona = "Branch Manager"` on the demo BM.
- Links the Employee to the Main Branch Cost Center so portal APIs return data.
- Idempotent — safe to re-run.

Run via:
  bench --site lms.localhost execute lms_saas.setup.bootstrap_books.fix_demo_bm
"""
import frappe


def run():
	frappe.msgprint("Books & import module is in place. Run `bench restart` to be safe.")


def fix_demo_bm():
	user = "demo.lms.branch@example.com"
	emp = frappe.db.get_value("Employee", {"user_id": user}, "name")
	if not emp:
		print("No Employee record for", user)
		return
	doc = frappe.get_doc("Employee", emp)
	branch = doc.branch or doc.custom_lms_branch
	if not branch:
		branch = "Main Branch - LMS Demo Co"
	if not frappe.get_meta("Employee").has_field("custom_lms_branch"):
		doc.branch = branch
	else:
		doc.custom_lms_branch = branch
	if frappe.get_meta("Employee").has_field("custom_lms_persona"):
		doc.custom_lms_persona = "Branch Manager"
	doc.flags.ignore_permissions = True
	doc.save(ignore_permissions=True)
	print("OK", emp, branch)

