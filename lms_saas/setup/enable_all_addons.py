"""Enable all registered addons for testing.

Usage: bench --site lms.localhost execute lms_saas.setup.enable_all_addons.run
"""

import frappe


def run():
	from lms_saas.utils.addons import ADDON_REGISTRY

	# Ensure the LMS Addon Settings singleton exists and is populated
	doc = frappe.get_single("LMS Addon Settings")

	# Add missing rows / enable existing ones
	existing_keys = {row.addon_key for row in (doc.addons or [])}
	for key, spec in ADDON_REGISTRY.items():
		if key not in existing_keys:
			doc.append(
				"addons",
				{
					"addon_key": key,
					"addon_label": str(spec.get("label", key)),
					"description": str(spec.get("description", "")),
					"enabled": 1,
				},
			)
		else:
			for row in doc.addons:
				if row.addon_key == key:
					row.enabled = 1

	doc.flags.ignore_permissions = True
	doc.save()
	# on_update hook writes site_config.lms_addons — no conf.save() needed

	frappe.db.commit()
	frappe.clear_cache()

	enabled = sum(1 for row in doc.addons if row.enabled)
	return {"ok": True, "total_addons": len(doc.addons or []), "enabled": enabled}
