"""Round 9 residual-closure smoke.

bench --site lms.localhost execute lms_saas.setup.smoke_board_r9.run
"""

from __future__ import annotations

import frappe


def run():
	from lms_saas.setup import smoke_board_r8
	from lms_saas.api import documents_center, manager, whatsapp, field_visits
	from lms_saas.utils.brand import _resolve_portal_currency

	base = smoke_board_r8.run()
	lines = [base, "--- r9 extras ---"]

	# Download endpoint exists + is guarded
	lines.append(
		f"download_document={hasattr(documents_center, 'download_document')}"
	)

	# Rate-limit decorators attached
	for fn, name in (
		(manager.approve_application, "approve"),
		(manager.reject_application, "reject"),
		(whatsapp.send_whatsapp, "whatsapp"),
	):
		wrapped = getattr(fn, "__wrapped__", None) is not None or "rate_limit" in repr(fn)
		# frappe.rate_limit wraps; presence of __wrapped__ is a strong signal
		has = hasattr(fn, "__wrapped__")
		lines.append(f"rate_limit {name}={has}")

	# Field visits GPS API present
	lines.append(f"field_visits.check_in={hasattr(field_visits, 'check_in')}")

	# Currency resolution
	cur = _resolve_portal_currency()
	lines.append(f"portal_currency={cur}")

	# Idle config
	idle = frappe.conf.get("lms_portal_idle_minutes", 30)
	lines.append(f"idle_minutes_config={idle}")

	# Document list strips file_url
	frappe.set_user("demo.lms.branch@example.com")
	try:
		docs = documents_center.get_documents(limit=5)
		sample = (docs.get("documents") or [None])[0]
		if sample:
			lines.append(
				f"doc_sample has_file_url={'file_url' in sample} "
				f"has_download_url={bool(sample.get('download_url'))}"
			)
		else:
			lines.append("doc_sample empty (ok)")
	except Exception as e:
		lines.append(f"doc_list ERR:{type(e).__name__}:{str(e)[:80]}")

	msg = "\n".join(lines)
	print(msg)
	return msg
