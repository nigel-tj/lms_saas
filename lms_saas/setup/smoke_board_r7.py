"""One-shot smoke for Round 7 board polish. Run via:
bench --site lms.localhost execute lms_saas.setup.smoke_board_r7.run
"""

from __future__ import annotations

import frappe


def run():
	from lms_saas.utils.portal import resolve_portal_persona
	from lms_saas.www.lms import index as idx
	from lms_saas.www.lms import apply as apply_page
	from lms_saas.www.lms import collect as collect_page
	from lms_saas.api import inventory, tasks

	lines = []
	cases = [
		("demo.lms.branch@example.com", "Manager", "/lms/manager"),
		("demo.lms.officer@example.com", "Officer", "/lms/officer"),
		("demo.lms.collector@example.com", "Collector", "/lms/collect"),
		("demo.lms.borrower@example.com", "Borrower", None),
	]
	for email, label, expect in cases:
		frappe.set_user(email)
		persona = resolve_portal_persona()
		frappe.local.flags.redirect_location = None
		try:
			idx.get_context(frappe._dict())
			got = "RENDER"
		except frappe.Redirect:
			got = frappe.local.flags.redirect_location
		frappe.local.flags.redirect_location = None
		try:
			apply_page.get_context(frappe._dict())
			apply_got = "RENDER"
		except frappe.Redirect:
			apply_got = frappe.local.flags.redirect_location
		frappe.local.flags.redirect_location = None
		try:
			collect_page.get_context(frappe._dict())
			collect_got = "RENDER"
		except frappe.Redirect:
			collect_got = frappe.local.flags.redirect_location
		except Exception as e:
			collect_got = f"ERR:{type(e).__name__}"
		ok = (got == expect) if expect else (got == "RENDER")
		lines.append(
			f"{label}: persona={persona} /lms={got} ok={ok} apply={apply_got} collect={collect_got}"
		)

	frappe.set_user("demo.lms.branch@example.com")
	stats = inventory.get_inventory_stats()
	board = tasks.get_task_board()
	overdue_cards = sum(1 for col in board["board"].values() for t in col if t.get("is_overdue"))
	lines.append(f"inventory_stats={stats}")
	lines.append(f"tasks overdue KPI={tasks.get_task_stats().get('overdue')} cards={overdue_cards}")
	msg = "\n".join(lines)
	print(msg)
	return msg
