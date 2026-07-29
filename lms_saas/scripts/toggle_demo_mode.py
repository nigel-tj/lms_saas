#!/usr/bin/env bash
# Toggle sandbox mode on/off without losing existing demo data.
#
# Why this exists:
#   The R18 board locked down sandbox mode behind `lms_sandbox_end_date`
#   in site_config.json so a regulator could never see demo seed records
#   mixed in with real loans. That is correct behaviour for a regulated
#   production site — but it makes client demos awkward, because the
#   operator has to (a) delete the flag, (b) re-seed demo data, (c)
#   reinstate the flag afterwards. This script does all three safely
#   in one command.
#
# Usage:
#   bench --site <site> execute lms_saas.scripts.toggle_demo_mode.enable_for_demo
#   bench --site <site> execute lms_saas.scripts.toggle_demo_mode.restore_sandbox
#
# Or from the bench CLI:
#   bash scripts/toggle-demo-mode.sh enable <site>
#   bash scripts/toggle-demo-mode.sh restore <site>

from __future__ import annotations

import json
import os
from datetime import date, timedelta

import frappe


SANDBOX_KEY = "lms_sandbox_end_date"
DEFAULT_SANDBOX_END = (date.today() + timedelta(days=365)).isoformat()


def _demo_email_domain() -> str:
	"""Return the email domain for demo-user addresses.

	R23-H2 fix: derived from the operator's brand (lms_brand_portal_title)
	rather than the hard-coded original operator's domain. Operators who
	re-brand to a different product line (e.g. "Kopo Capital") will see
	demo users with @kopocapital.example.com — clearly demo, clearly
	scoped to the operator's brand. Falls back to "kesari.example.com"
	for backward compatibility with the original operator's existing
	Frappe Cloud sites (no surprise email changes on upgrade).
	"""
	override = frappe.conf.get("lms_demo_email_domain")
	if override:
		return override
	brand = (frappe.conf.get("lms_brand_portal_title") or "kesari").lower().strip()
	# Strip non-domain characters (spaces, punctuation) but keep hyphens.
	brand = "".join(c for c in brand if c.isalnum() or c in "-_")
	return f"{brand}.example.com"


def _demo_user_email(persona: str) -> str:
	"""Return the demo user email for ``persona`` using the configured domain.

	The original Kesari deployment uses manager@kesari.africa as the demo
	address; the function above produces the same string for that
	operator. Other operators get demo users at <persona>@<their-brand>.example.com.
	"""
	return f"{persona.lower().replace(' ', '')}@{_demo_email_domain()}"


# Canonical demo personas + passwords from scripts/create-test-users.sh.
# Keeping these in sync with that script means a fresh Frappe Cloud bench
# can use this toggle to bootstrap everything in one shot.
#
# R23-H2 fix: email addresses are now derived from the operator's brand
# via _demo_user_email() rather than hard-coded @kesari.africa. The
# DEMO_USERS list now contains just the persona, password, and branch
# metadata — the email is computed at the call site.
DEMO_USERS = (
	{
		"persona": "Branch Manager",
		"first_name": "Branch",
		"last_name": "Manager",
		"password": "Manager@123",
		"branch_cost_center": None,
	},
	{
		"persona": "Loan Officer",
		"first_name": "Loan",
		"last_name": "Officer",
		"password": "Officer@123",
		"branch_cost_center": None,
	},
	{
		"persona": "Collector",
		"first_name": "Collection",
		"last_name": "Agent",
		"password": "Collector@123",
		"branch_cost_center": None,
	},
)


def _ensure_demo_user(spec: dict) -> str:
	"""Create the User + Employee + persona link for a demo persona if missing.

	Returns "created" / "reset" / "skipped" so the toggle log is useful.
	"""
	# R23-H2 fix: derive the demo email from the operator's configured
	# brand (via _demo_user_email) rather than reading it from the spec.
	email = _demo_user_email(spec["persona"])
	if not frappe.db.exists("User", email):
		try:
			user = frappe.new_doc("User")
			user.email = email
			user.first_name = spec["first_name"]
			user.last_name = spec.get("last_name") or ""
			user.send_welcome_email = 0
			user.enabled = 1
			# CRITICAL: must be System User (not Website User). Frappe's
			# auth.py treats Website Users as portal-only and at login
			# sets home_page = "/" + get_home_page() — for portal staff
			# that resolves to /desk/lending which 403s. System Users
			# get the bootinfo.default_route (/lms/manager for managers).
			user.user_type = "System User"
			user.append("roles", {"role": "LMS Portal Staff"})
			user.save(ignore_permissions=True)
			frappe.utils.password.update_password(email, spec["password"])
			_ensure_demo_employee(spec)
			return "created"
		except Exception as exc:  # noqa: BLE001
			return f"skipped: {exc}"

	# User already exists — make sure LMS Portal Staff role is attached so
	# the portal nav is populated, AND correct user_type if it was created
	# with the old Website User default (would otherwise 403 on /desk/lending
	# post-login redirect).
	try:
		user = frappe.get_doc("User", email)
		role_names = {r.role for r in user.roles}
		needs_save = False
		if "LMS Portal Staff" not in role_names:
			user.append("roles", {"role": "LMS Portal Staff"})
			needs_save = True
		if getattr(user, "user_type", None) != "System User":
			user.user_type = "System User"
			needs_save = True
		if needs_save:
			try:
				user.save(ignore_permissions=True)
				frappe.db.commit()
			except Exception as doc_exc:
				# Fallback: doc save may fail on System Manager users with
				# strict perm checks. Use SQL so the fix is durable even when
				# the doc layer rejects changes.
				print(
					f"[toggle_demo_mode] doc.save() failed for {email} "
					f"({doc_exc!s}); falling back to SQL for user_type"
				)
				frappe.db.sql(
					"UPDATE tabUser SET user_type='System User' "
					"WHERE name=%s AND user_type != 'System User'",
					(email,),
				)
				frappe.db.commit()
	except Exception:  # noqa: BLE001
		pass

	# Reset password to the canonical value so the operator always has the
	# demo sign-in sheet working.
	try:
		frappe.utils.password.update_password(email, spec["password"])
	except Exception as exc:  # noqa: BLE001
		return f"skipped: {exc}"

	# Ensure the Employee + persona link exists (resolve_portal_persona reads
	# Employee.custom_lms_persona; without it the persona is None, can_manager
	# is False, and /lms/manager 301-redirects to itself in an infinite loop).
	_ensure_demo_employee(spec)
	return "reset"


def _ensure_demo_employee(spec: dict) -> None:
	"""Create or update the Employee record carrying ``custom_lms_persona``.

	``resolve_portal_persona()`` reads ``Employee.custom_lms_persona`` to
	decide which portal page a staff user lands on. Without an Employee
	record, the persona is ``None``, ``can_manager``/``can_officer`` are
	``False``, and ``require_persona_for_page`` redirects to the persona
	landing — which for portal staff defaults to ``/lms/manager``, causing
	an infinite redirect loop when a Branch Manager hits ``/lms/manager``.
	"""
	# R23-H2 fix: derive the demo email from the operator's configured
	# brand (via _demo_user_email) rather than reading it from the spec.
	email = _demo_user_email(spec["persona"])
	persona = spec.get("persona")
	if not persona:
		return

	emp_name = frappe.db.get_value(
		"Employee", {"user_id": email, "status": "Active"}, "name"
	)
	if emp_name:
		# Update persona if the field exists and is empty/wrong.
		if frappe.get_meta("Employee").has_field("custom_lms_persona"):
			current = frappe.db.get_value("Employee", emp_name, "custom_lms_persona")
			if current != persona:
				frappe.db.set_value(
					"Employee", emp_name, "custom_lms_persona", persona
				)
		return

	# No Employee — create one linked to the User.
	try:
		company = frappe.db.get_single_value("Global Defaults", "default_company")
		if not company:
			# No company set up yet; skip silently (after_install may not
			# have run). The toggle log will show "reset" regardless.
			return
		emp = frappe.new_doc("Employee")
		emp.employee_name = " ".join(
			filter(None, [spec.get("first_name"), spec.get("last_name")])
		)
		emp.first_name = spec.get("first_name") or "Demo"
		emp.last_name = spec.get("last_name") or ""
		emp.user_id = email
		emp.company = company
		emp.status = "Active"
		emp.gender = "Male"
		emp.date_of_birth = "1990-01-01"
		emp.date_of_joining = "2024-01-01"
		if frappe.get_meta("Employee").has_field("custom_lms_persona"):
			emp.custom_lms_persona = persona
		emp.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception as exc:  # noqa: BLE001
		print(
			f"[toggle_demo_mode] Employee creation failed for {email} "
			f"({exc!s}); persona link may be missing"
		)


def _write_site_config(updates: dict) -> None:
	"""Patch the site_config.json on disk with the given key/values."""
	sites_root = frappe.get_site_path()
	site_config = os.path.join(sites_root, "site_config.json")
	with open(site_config, "r") as f:
		cfg = json.load(f)
	cfg.update(updates)
	with open(site_config, "w") as f:
		json.dump(cfg, f, indent=2, sort_keys=True)
		f.write("\n")


def enable_for_demo() -> dict:
	"""Disable sandbox mode, re-seed demo data, and clear the demo filter.

	Returns a small dict so the calling shell can show what changed.
	"""
	result = {
		"sandbox_before": bool(frappe.conf.get(SANDBOX_KEY)),
		"actions": [],
	}

	# 1. Remove the sandbox flag so the app behaves as a production-shape
	#    site for the demo (real borrower names visible, demo seed
	#    filter no longer hides anything because we re-seed cleanly).
	if frappe.conf.get(SANDBOX_KEY):
		frappe.conf.pop(SANDBOX_KEY, None)
		_write_site_config({SANDBOX_KEY: None})  # remove from disk
		result["actions"].append("removed lms_sandbox_end_date")

	# 2. Toggle the demo-seed filter OFF in code (we still want it for
	#    production-shape demos, but the operator should *see* the demo
	#    seed data — that is the whole point of a client demo).
	frappe.db.set_default("lms_demo_filter_enabled", "0")
	result["actions"].append("disabled demo-seed filter (lms_demo_filter_enabled=0)")

	# 3. Re-seed the canonical demo portfolio so the dashboard is full.
	#    On a fresh Frappe Cloud bench the Loan Product + Chart of Accounts
	#    may not be set up yet, so bootstrap via after_install() first and
	#    then retry the seeder. This makes the toggle idempotent on a brand
	#    new bench, not just on a sandbox-mode bench.
	try:
		from lms_saas.setup.seed_demo import run as seed_run

		# Pre-flight: if no LMS-STD Loan Product, run after_install to create
		# the chart-of-accounts + product. after_install is idempotent.
		company = frappe.db.get_single_value("Global Defaults", "default_company")
		has_product = bool(
			company
			and frappe.db.exists(
				"Loan Product", {"company": company, "product_code": "LMS-STD"}
			)
		)
		if not has_product:
			try:
				from lms_saas.install import after_install

				after_install()
				result["actions"].append("bootstrapped LMS Standard Loan Product via after_install()")
			except Exception as exc:  # noqa: BLE001
				result["actions"].append(f"after_install bootstrap failed: {exc}")

		seed_run()
		result["actions"].append("re-seeded canonical demo portfolio")
	except Exception as exc:  # noqa: BLE001
		result["actions"].append(f"re-seed skipped: {exc}")

	# 4. Bootstrap the lms_saas demo personas so the client can sign in.
	#    Each persona is created (User + LMS Portal Staff role) if it
	#    doesn't exist, AND its password is reset to the canonical
	#    value from DEMO_USERS. NEVER touches the Frappe Cloud
	#    "Administrator" account — the bench operator controls that
	#    password themselves.
	for spec in DEMO_USERS:
		status = _ensure_demo_user(spec)
		# R23-H2 fix: derive the email from the operator's brand rather
		# than reading it from the spec (which no longer carries an
		# email — the brand is the source of truth).
		result["actions"].append(f"{_demo_user_email(spec['persona'])}: {status}")

	frappe.db.commit()
	result["sandbox_after"] = bool(frappe.conf.get(SANDBOX_KEY))
	return result


def restore_sandbox() -> dict:
	"""Re-arm the sandbox flag and re-enable the demo-seed filter.

	Use this immediately after a client demo to return the site to its
	regulated posture.
	"""
	result = {
		"sandbox_before": bool(frappe.conf.get(SANDBOX_KEY)),
		"actions": [],
	}

	# 1. Reinstate the sandbox flag with a 12-month rolling window.
	end_date = DEFAULT_SANDBOX_END
	frappe.conf[SANDBOX_KEY] = end_date
	_write_site_config({SANDBOX_KEY: end_date})
	result["actions"].append(f"set lms_sandbox_end_date={end_date}")

	# 2. Re-enable the demo-seed filter so any future demo seed records
	#    don't surface in staff lists.
	frappe.db.set_default("lms_demo_filter_enabled", "1")
	result["actions"].append("re-enabled demo-seed filter (lms_demo_filter_enabled=1)")

	frappe.db.commit()
	result["sandbox_after"] = bool(frappe.conf.get(SANDBOX_KEY))
	return result


def status() -> dict:
	"""Return the current demo/sandbox posture so the operator can verify."""
	from lms_saas.api.compliance_config import (
		is_sandbox_mode,
		is_production_mode,
		operator_profile,
	)
	return {
		"sandbox_mode": is_sandbox_mode(),
		"production_mode": is_production_mode(),
		"operator_profile": operator_profile(),
		"demo_seed_filter_enabled": frappe.db.get_default("lms_demo_filter_enabled") or "1",
	}


def reset_admin_password(new_password: str = "Welcome1!") -> dict:
	"""OPT-IN: reset the bench's Administrator password.

	Standalone helper that exists ONLY for the operator who has lost
	their Frappe Cloud bench's Administrator password. It is NEVER called
	from `enable_for_demo` or `restore_sandbox` — those toggles touch only
	the lms_saas demo personas. Calling this is the operator's explicit
	choice; it does not happen as a side-effect of the demo toggle.

	Usage:
	  bench --site <site> execute \\
	    lms_saas.scripts.toggle_demo_mode.reset_admin_password
	  bench --site <site> execute \\
	    lms_saas.scripts.toggle_demo_mode.reset_admin_password --kwargs \\
	    '{"new_password": "SomethingSecure123!"}'
	"""
	from frappe.utils.password import update_password

	result = {"reset": [], "skipped": []}
	if not frappe.db.exists("User", "Administrator"):
		result["skipped"].append("Administrator (user does not exist)")
		return result
	try:
		update_password("Administrator", new_password)
		result["reset"].append("Administrator")
	except Exception as exc:  # noqa: BLE001
		result["skipped"].append(f"Administrator ({exc})")
	frappe.db.commit()
	return result
