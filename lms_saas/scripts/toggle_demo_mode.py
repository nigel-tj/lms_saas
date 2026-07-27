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
	try:
		from lms_saas.setup.seed_demo import run as seed_run
		seed_run()
		result["actions"].append("re-seeded canonical demo portfolio")
	except Exception as exc:  # noqa: BLE001
		result["actions"].append(f"re-seed skipped: {exc}")

	# 4. Ensure the demo admin user has a known password so the demo
	#    client can sign in.
	try:
		from frappe.utils.password import update_password
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
