"""Phase 4.4 — one-time script to rewrite legacy role references in JSON fixtures.

Run with::

    bench --site lms.localhost execute lms_saas.setup.migrate_legacy_role_names.run

Rewrites every ``"role": "LMS <X>"`` in:

* ``apps/lms_saas/lms_saas/doctype/<dt>/<dt>.json`` (DocType ``permissions`` rows)
* ``apps/lms_saas/lms_saas/report/<report>/<report>.json`` (Report ``roles`` rows)

…to use the new role-name mapping:

* ``LMS Admin``            -> ``System Manager``
* ``LMS Branch Manager``   -> ``LMS Portal Staff``
* ``LMS Loan Officer``     -> ``LMS Portal Staff``
* ``LMS Collector``        -> ``LMS Portal Staff``

The on-disk JSON is left unchanged (the in-DB migration is handled by the
patch in ``patches/v15_1/migrate_legacy_role_perms.py``). This script
prints a per-file report so a developer can hand-verify before regenerating
the JSONs. To actually rewrite the JSONs on disk, run::

    bench --site lms.localhost execute lms_saas.setup.migrate_legacy_role_names.apply

Use ``dry_run=True`` (the default) to see what would change without writing.
"""

from __future__ import annotations

import json
import os

import frappe

LEGACY_ROLES = ("LMS Admin", "LMS Branch Manager", "LMS Loan Officer", "LMS Collector")

ROLE_MAP = {
	"LMS Admin": "System Manager",
	"LMS Branch Manager": "LMS Portal Staff",
	"LMS Loan Officer": "LMS Portal Staff",
	"LMS Collector": "LMS Portal Staff",
}


def _collect_target_files():
	"""Return the list of JSON files that may reference legacy role names."""
	app_path = frappe.get_app_path("lms_saas")
	roots = (
		os.path.join(app_path, "lms_saas", "doctype"),
		os.path.join(app_path, "lms_saas", "report"),
	)
	files = []
	for root in roots:
		if not os.path.isdir(root):
			continue
		for entry in sorted(os.listdir(root)):
			sub = os.path.join(root, entry)
			if not os.path.isdir(sub):
				continue
			for name in os.listdir(sub):
				if name.endswith(".json"):
					files.append(os.path.join(sub, name))
	return files


def _scan(data, path=()):
	"""Yield ``(path_tuple, current_role_string)`` for every role-shaped field."""
	if isinstance(data, dict):
		role = data.get("role")
		if isinstance(role, str) and role in LEGACY_ROLES:
			yield (path, role)
		for k, v in data.items():
			yield from _scan(v, path + (k,))
	elif isinstance(data, list):
		for i, v in enumerate(data):
			yield from _scan(v, path + (i,))


def _apply(data, mapping):
	"""Replace legacy role values in-place; return (count, new_data)."""
	count = 0
	for path, role in list(_scan(data)):
		new_role = mapping[role]
		# Walk to the dict and update.
		node = data
		for key in path[:-1]:
			node = node[key]
		node[path[-1]] = new_role
		count += 1
	return count


def run(dry_run=True):
	"""Report what would change per file. Returns a dict of {path: count}."""
	app_path = frappe.get_app_path("lms_saas")
	report = {}
	for path in _collect_target_files():
		with open(path, encoding="utf-8") as fh:
			data = json.load(fh)
		count = len(list(_scan(data)))
		if count:
			report[os.path.relpath(path, app_path)] = count
	if dry_run:
		print("Legacy role references (dry run — no files modified):")
		for k, v in report.items():
			print(f"  {k}: {v} row(s)")
		print(f"Total: {sum(report.values())} role rows across {len(report)} file(s)")
		return report
	return apply(report)


def apply(report=None):
	"""Rewrite the JSONs in place. Idempotent — already-migrated files are skipped."""
	app_path = frappe.get_app_path("lms_saas")
	touched = []
	for path in _collect_target_files():
		with open(path, encoding="utf-8") as fh:
			data = json.load(fh)
		count = _apply(data, ROLE_MAP)
		if count:
			with open(path, "w", encoding="utf-8") as fh:
				json.dump(data, fh, indent=1, ensure_ascii=False)
				fh.write("\n")
			touched.append((os.path.relpath(path, app_path), count))
	print(f"Rewrote {len(touched)} file(s):")
	for k, v in touched:
		print(f"  {k}: {v} role row(s)")
	return {"touched": touched}


if __name__ == "__main__":
	run(dry_run=True)
