"""R42: deduplicate Contact primary emails corrupted by prior test runs.

The ``User.on_update → create_contact`` chain appended a primary email
each time a User was saved, and the LMS User Setup test's purge didn't
clean up the Contact's child table. This left Contacts with multiple
``is_primary=1`` email rows, which then caused
``Contact.validate → set_primary_email`` to throw "Only one Email ID
can be set as primary" on the next save.

This patch keeps only the first primary email per Contact. Idempotent.
"""

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.table_exists("Contact Email"):
		return
	# 1. Dedup primary emails
	rows = frappe.db.sql(
		"""SELECT parent, name FROM `tabContact Email`
		   WHERE is_primary = 1 AND parent IN (
		     SELECT parent FROM `tabContact Email`
		     WHERE is_primary = 1 GROUP BY parent HAVING COUNT(*) > 1
		   )
		   ORDER BY parent, name""",
		as_dict=True,
	)
	if rows:
		from collections import defaultdict

		by_parent = defaultdict(list)
		for r in rows:
			by_parent[r.parent].append(r.name)
		fixed = 0
		for parent, names in by_parent.items():
			for name in names[1:]:
				frappe.db.set_value("Contact Email", name, "is_primary", 0, update_modified=False)
				fixed += 1
		frappe.db.commit()
		print(f"R42: deduped {fixed} duplicate primary Contact emails")

	# 2. Dedup primary phones (is_primary_mobile_no)
	if frappe.db.table_exists("Contact Phone"):
		rows = frappe.db.sql(
			"""SELECT parent, name FROM `tabContact Phone`
			   WHERE is_primary_mobile_no = 1 AND parent IN (
			     SELECT parent FROM `tabContact Phone`
			     WHERE is_primary_mobile_no = 1 GROUP BY parent HAVING COUNT(*) > 1
			   )
			   ORDER BY parent, name""",
			as_dict=True,
		)
		if rows:
			from collections import defaultdict

			by_parent = defaultdict(list)
			for r in rows:
				by_parent[r.parent].append(r.name)
			fixed = 0
			for parent, names in by_parent.items():
				for name in names[1:]:
					frappe.db.set_value("Contact Phone", name, "is_primary_mobile_no", 0, update_modified=False)
					fixed += 1
			frappe.db.commit()
			print(f"R42: deduped {fixed} duplicate primary Contact mobile_nos")