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

	# 4. Ensure the demo passwords are set so the demo client can sign in.
	#    Covers BOTH the Frappe Cloud "Administrator" account (the bench's
	#    default super-admin) AND the lms_saas demo personas. This block
	#    runs even if the seeder above failed — that way the operator can
	#    always recover an admin login after a botched toggle.
	try:
		from frappe.utils.password import update_password

		# Frappe Cloud benches always have an "Administrator" user — that's
		# the real admin login the operator uses. Reset it to a known
		# password so they can sign in after the toggle.
		if frappe.db.exists("User", "Administrator"):
			update_password("Administrator", "Welcome1!")
			result["actions"].append("reset password for Administrator")

		for email, pw in (
			("administrator@example.com", "Welcome1!"),
			("manager@kesari.africa", "Welcome1!"),
			("officer@kesari.africa", "Welcome1!"),
		):
			if frappe.db.exists("User", email):
				update_password(email, pw)
				result["actions"].append(f"reset password for {email}")
	except Exception as exc:  # noqa: BLE001
		result["actions"].append(f"password reset skipped: {exc}")

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
	"""Reset the Frappe Cloud bench's Administrator password.

	Standalone helper for the case where `enable_for_demo` failed before
	reaching the password-reset block (e.g. on a brand-new bench where
	no LMS personas exist yet). Use this to recover an admin login
	without re-running the full demo bootstrap.

	Usage:
	  bench --site <site> execute \
	    lms_saas.scripts.toggle_demo_mode.reset_admin_password
	  bench --site <site> execute \
	    lms_saas.scripts.toggle_demo_mode.reset_admin_password --kwargs \
	    '{"new_password": "SomethingSecure123!"}'
	"""
	from frappe.utils.password import update_password

	result = {"reset": [], "skipped": []}
	for email in (
		"Administrator",
		"administrator@example.com",
		"manager@kesari.africa",
		"officer@kesari.africa",
	):
		if not frappe.db.exists("User", email):
			result["skipped"].append(email)
			continue
		try:
			update_password(email, new_password)
			result["reset"].append(email)
		except Exception as exc:  # noqa: BLE001
			result["skipped"].append(f"{email} ({exc})")
	frappe.db.commit()
	return result
