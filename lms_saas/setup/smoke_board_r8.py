"""One-shot smoke for Round 8 board polish. Run via:
bench --site lms.localhost execute lms_saas.setup.smoke_board_r8.run
"""

from __future__ import annotations

import frappe


def run():
	from lms_saas.utils.portal import resolve_portal_persona
	from lms_saas.utils.addons import ADDON_REGISTRY, is_addon_enabled
	from lms_saas.www.lms import index as idx
	from lms_saas.api import training, procurement, regulatory_hub, hr, payroll, inventory, tasks

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
		ok = (got == expect) if expect else (got == "RENDER")
		lines.append(f"{label}: persona={persona} /lms={got} ok={ok}")

	# Regulatory: Branch Manager must be allowed (read-only surface)
	reg_personas = ADDON_REGISTRY.get("regulatory_hub", {}).get("personas", [])
	lines.append(f"regulatory_personas={reg_personas} bm_allowed={'Branch Manager' in reg_personas}")

	frappe.set_user("demo.lms.branch@example.com")
	stats = regulatory_hub.get_regulatory_stats()
	branch = regulatory_hub.get_branch_summary()
	lines.append(
		"regulatory_stats keys="
		+ ",".join(sorted(stats.keys()))
		+ f" pending={stats.get('pending_submissions')} recipients={len(stats.get('compliance_recipients') or [])}"
		+ f" is_admin={stats.get('is_admin')}"
	)
	lines.append(
		f"branch_summary pending={branch.get('pending_submissions')} "
		f"line={str(branch.get('summary_line') or '')[:80]}"
	)

	# Training / Procurement: graceful _missing (never throw)
	tp = training.get_training_programs()
	pr = procurement.get_purchase_requests()
	tev = training.get_training_events(upcoming=False)
	lines.append(
		f"training _missing={bool(tp.get('_missing'))} programs={len(tp.get('programs') or [])} "
		f"events={len(tev.get('events') or [])}"
	)
	lines.append(
		f"procurement _missing={bool(pr.get('_missing'))} requests={len(pr.get('requests') or [])}"
	)

	# HR / Payroll zero-state payloads
	try:
		hd = hr.get_hr_dashboard()
		lines.append(f"hr_dashboard team_count={hd.get('team_count')} keys_ok={bool(hd)}")
	except Exception as e:
		lines.append(f"hr_dashboard ERR:{type(e).__name__}:{str(e)[:80]}")

	try:
		po = payroll.get_payroll_overview()
		lines.append(
			f"payroll_overview team={po.get('team_count')} slips={po.get('slip_count')}"
		)
	except Exception as e:
		lines.append(f"payroll_overview ERR:{type(e).__name__}:{str(e)[:80]}")

	inv = inventory.get_inventory_stats()
	board = tasks.get_task_board()
	overdue_cards = sum(1 for col in board["board"].values() for t in col if t.get("is_overdue"))
	lines.append(f"inventory_stats ok={bool(inv)}")
	lines.append(f"tasks overdue KPI={tasks.get_task_stats().get('overdue')} cards={overdue_cards}")

	# Addon flags for soft portals
	for key in ("training", "procurement", "regulatory_hub", "hr_management", "payroll", "whatsapp", "wallet_recon", "branch_analytics"):
		try:
			lines.append(f"addon {key} enabled={is_addon_enabled(key)}")
		except Exception:
			lines.append(f"addon {key} enabled=?")

	# Table presence (honest site readiness). table_exists expects DocType name.
	for dt in ("Training Program", "Material Request", "LMS Regulatory Submission"):
		exists = bool(frappe.db.exists("DocType", dt))
		table = bool(frappe.db.table_exists(dt))
		lines.append(f"doctype {dt}: exists={exists} table={table}")

	msg = "\n".join(lines)
	print(msg)
	return msg
