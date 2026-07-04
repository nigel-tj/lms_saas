"""Website auth overrides (branded logout)."""

from __future__ import annotations

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def web_logout():
	"""Replace Frappe's generic logout page with branded /login."""
	frappe.local.login_manager.logout()
	frappe.db.commit()
	# cmd= requests use handler JSON path; Redirect exception does not apply there.
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = "/login?logged_out=1"

