"""Debug LMS Operations workspace shortcuts (bench execute lms_saas.setup.debug_workspace.run)."""

import frappe
from frappe.desk.desktop import Workspace


def run():
	frappe.set_user("Administrator")
	w = Workspace({"name": "LMS Operations", "title": "LMS Operations", "public": 1})
	w.build_workspace()
	items = w.shortcuts.get("items", [])
	print("shortcut_count", len(items))
	for item in items:
		print(item.get("label"), item.get("type"), item.get("link_to"))
