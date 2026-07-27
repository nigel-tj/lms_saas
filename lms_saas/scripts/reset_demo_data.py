"""Reset the demo seed data for the LMS sandbox site.

R18-1: When the operator clicks "Reset demo data" on the LMS Admin help
page, this script wipes the seeded Loan Applications and Borrowers and
re-seeds them from `setup/seed_demo.py` (or any other seed the site ships
with). Used so that staff-list views never show stale demo state to a
regulator and operators can demonstrate the sandbox cleanly.

Usage:
    bench --site lms.localhost execute lms_saas.scripts.reset_demo_data.run
"""

from __future__ import annotations

import frappe


DEMO_APPLICANT_PATTERNS = (
	"%Test%",
	"%R14-APP%",
	"%Borrower 003%",
	"%Borrower 002%",
	"%Demo%",
)


def _is_demo(name: str) -> bool:
	if not name:
		return False
	needle = name.lower()
	return any(p.strip("%").lower() in needle for p in DEMO_APPLICANT_PATTERNS)


def _delete_demo_loan_applications() -> int:
	"""Cancel and delete every Loan Application whose applicant looks like demo seed."""
	apps = frappe.get_all(
		"Loan Application",
		filters={"docstatus": ("<", 2)},
		fields=["name", "applicant", "docstatus"],
		limit_page_length=500,
	)
	deleted = 0
	for app in apps:
		customer_name = (
			frappe.db.get_value("Customer", app.applicant, "customer_name") if app.applicant else ""
		)
		if _is_demo(customer_name) or _is_demo(app.applicant):
			try:
				doc = frappe.get_doc("Loan Application", app.name)
				if doc.docstatus == 1:
					doc.cancel()
				doc.delete()
				deleted += 1
			except Exception as exc:  # noqa: BLE001
				frappe.log_error(f"reset_demo_data: could not delete {app.name}: {exc}")
	return deleted


def _delete_demo_customers() -> int:
	"""Delete demo Customer records (and the linked Contact)."""
	customers = frappe.get_all(
		"Customer",
		filters={"customer_name": ("like", "%Test%")},
		fields=["name", "customer_name"],
		limit_page_length=500,
	)
	# add the explicit patterns that don't match "Test" prefix
	extra = frappe.get_all(
		"Customer",
		filters={"customer_name": ("like", "%R14-APP%")},
		fields=["name", "customer_name"],
		limit_page_length=500,
	)
	seen = set()
	deleted = 0
	for c in customers + extra:
		if c["name"] in seen:
			continue
		seen.add(c["name"])
		try:
			frappe.delete_doc("Customer", c["name"], force=True, ignore_permissions=True)
			deleted += 1
		except Exception as exc:  # noqa: BLE001
			frappe.log_error(f"reset_demo_data: could not delete Customer {c['name']}: {exc}")
	return deleted


def run() -> dict:
	"""Wipe demo seed data and re-run the standard seed."""
	if not frappe.db.table_exists("Customer"):
		return {"ok": False, "reason": "Customer table missing"}

	deleted_apps = _delete_demo_loan_applications()
	deleted_customers = _delete_demo_customers()

	# Re-seed if the canonical seeder is installed.
	try:
		from lms_saas.setup.seed_demo import run as seed_demo_run  # type: ignore
		seed_demo_run()
		seeded = True
	except Exception as exc:  # noqa: BLE001
		seeded = False
		frappe.log_error(f"reset_demo_data: re-seed failed: {exc}")

	frappe.db.commit()
	return {
		"ok": True,
		"deleted_loan_applications": deleted_apps,
		"deleted_customers": deleted_customers,
		"reseeded": seeded,
	}
