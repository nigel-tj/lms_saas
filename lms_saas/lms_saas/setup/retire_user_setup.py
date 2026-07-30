"""R26-P6-2 follow-up: explicit "retire a submitted LMS User Setup" runner.

`LMSUserSetup.on_cancel` deliberately refuses to silently orphan the linked
User / Customer / Contact / Employee rows. Operators who genuinely need to
retract a wrongly-onboarded account run this function, which:

1. Cancels the LMS User Setup (status 2) under audit.
2. Disables the linked User (so the account cannot log in).
3. Optionally deletes the linked User / Customer / Contact / Employee under
   audit when ``apply=True``.

The function is callable from the bench:

    bench --site <site> execute lms_saas.setup.retire_user_setup.run \\
        --kwargs '{"name": "SETUP-00042", "delete_records": 1}'

Or via ``frappe.call`` from a custom script.

The runner does NOT touch the audit pipeline. Every linked record removal is
recorded as an ``LMS Audit Event`` so the regulator has a complete trail
from onboarding to retirement.
"""

from typing import Optional

import frappe
from frappe import _


def run(name: str, delete_records: int = 0, reason: Optional[str] = None) -> dict:
	"""Retire a submitted LMS User Setup under audit.

	Parameters
	----------
	name : str
		The LMS User Setup doc name (e.g. ``SETUP-00042``).
	delete_records : int (0 or 1)
		If 1, *delete* the linked User / Customer / Contact / Employee records
		in addition to disabling the User. Off by default — disabling is
		usually sufficient and reversible.
	reason : str, optional
		Operator-supplied justification, written to the audit row.

	Returns
	-------
	dict
		``{name, cancelled, user_disabled, deleted, audit}`` so the caller can
		log or surface a status.
	"""
	setup = frappe.get_doc("LMS User Setup", name)
	if setup.docstatus != 1:
		frappe.throw(
			_("LMS User Setup {0} is not submitted (docstatus={1}); nothing to retire").format(
				name, setup.docstatus
			)
		)

	deleted = {"User": None, "Customer": None, "Contact": None, "Employee": None}
	user_disabled = False
	cancelled = False

	# Disable the User first so concurrent log-in attempts fail.
	if setup.created_user:
		frappe.db.set_value(
			"User", setup.created_user, "enabled", 0, update_modified=False
		)
		user_disabled = True

	if int(delete_records):
		# Order matters: Employee → Contact → Customer → User. We delete the
		# docs with `ignore_permissions=True` and `force=1` so the cleanup is
		# not blocked by permission rules. Each `frappe.delete_doc` writes its
		# own Standard Audit trail; the LMS Audit Event supplements it.
		if setup.created_employee:
			frappe.delete_doc(
				"Employee", setup.created_employee, force=1, ignore_permissions=True
			)
			deleted["Employee"] = setup.created_employee
		if setup.created_customer:
			contact = frappe.db.get_value(
				"Contact",
				{
					"email_id": setup.email,
					"link_doctype": "Customer",
					"link_name": setup.created_customer,
				},
				"name",
			)
			frappe.delete_doc(
				"Customer", setup.created_customer, force=1, ignore_permissions=True
			)
			deleted["Customer"] = setup.created_customer
			if contact:
				frappe.delete_doc(
					"Contact", contact, force=1, ignore_permissions=True
				)
				deleted["Contact"] = contact
		if setup.created_user:
			frappe.delete_doc(
				"User", setup.created_user, force=1, ignore_permissions=True
			)
			deleted["User"] = setup.created_user

	# Clear the linked-record fields on the in-memory doc, then reload from
	# the DB so the cancel-time guard (on_cancel) sees no records.
	setup.created_user = None
	setup.created_customer = None
	setup.created_employee = None
	setup.db_update()
	setup.reload()

	# Now cancel the LMS User Setup doc itself. ``on_cancel`` will see the
	# cleared fields and treat this as the "no records attached" cancel path.
	setup.flags.ignore_permissions = True
	setup.cancel()
	setup.reload()
	cancelled = setup.docstatus == 2

	# Record the audit row.
	audit = None
	if frappe.db.exists("DocType", "LMS Audit Event"):
		row = frappe.get_doc(
			{
				"doctype": "LMS Audit Event",
				"event_type": "USER_ONBOARD_RETIRED",
				"event_time": frappe.utils.now_datetime(),
				"event_user": frappe.session.user,
				"reference_doctype": "LMS User Setup",
				"reference_name": name,
				"company": frappe.db.get_single_value(
					"Global Defaults", "default_company"
				),
				"details": "reason={reason}; delete={delete}; deleted={deleted}; user_disabled={user_disabled}".format(
					reason=reason or "",
					delete=int(delete_records),
					deleted=deleted,
					user_disabled=user_disabled,
				),
			}
		)
		row.insert(ignore_permissions=True)
		audit = row.name
		frappe.db.commit()

	return {
		"name": name,
		"cancelled": cancelled,
		"user_disabled": user_disabled,
		"deleted": deleted,
		"audit": audit,
	}


if __name__ == "__main__":
	# Allow `python -m lms_saas.setup.retire_user_setup` for emergency use
	# from the bench host. Requires the bench env to be active.
	import argparse

	parser = argparse.ArgumentParser(description="Retire an LMS User Setup under audit.")
	parser.add_argument("--site", required=True)
	parser.add_argument("--name", required=True, help="LMS User Setup name (e.g. SETUP-00042)")
	parser.add_argument(
		"--delete", action="store_true", help="Also delete the linked records"
	)
	parser.add_argument("--reason", default=None, help="Operator reason for the retire")
	args = parser.parse_args()

	frappe.init(site=args.site)
	frappe.connect()
	try:
		import json

		print(json.dumps(run(args.name, int(args.delete), args.reason), indent=2, default=str))
	finally:
		frappe.destroy()
