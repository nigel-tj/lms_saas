"""Best-effort sync for DocTypes that exist without DB tables.

Run: bench --site lms.localhost execute lms_saas.setup.try_sync_missing_tables.run

Never edits frappe/erpnext core. Safe to re-run.
"""

from __future__ import annotations

import frappe


TARGETS = (
	"Training Program",
	"Training Event",
	"Training Result",
	"Material Request",
	"Purchase Order",
	"Supplier",
)


def run():
	results = []
	for dt in TARGETS:
		exists = bool(frappe.db.exists("DocType", dt))
		table_before = bool(frappe.db.table_exists(dt)) if exists else False
		if not exists:
			results.append({"doctype": dt, "status": "missing_doctype"})
			continue
		if table_before:
			results.append({"doctype": dt, "status": "ok", "table": True})
			continue
		try:
			frappe.reload_doctype(dt, force=True)
			frappe.db.updatedb(dt)
			frappe.db.commit()
			table_after = bool(frappe.db.table_exists(dt))
			results.append(
				{
					"doctype": dt,
					"status": "synced" if table_after else "sync_no_table",
					"table": table_after,
				}
			)
		except Exception as e:
			results.append(
				{
					"doctype": dt,
					"status": "error",
					"error": f"{type(e).__name__}: {str(e)[:160]}",
				}
			)
	print(results)
	return results
