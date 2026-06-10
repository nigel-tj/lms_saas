"""Role-based screen access audit for LMS workspaces and shortcuts.

Run:
  bench --site lms.localhost execute lms_saas.setup.verify_access.run_all
"""

from __future__ import annotations

import frappe
from frappe import _

from lms_saas.install import LMS_NAV_SPEC, ORIGINATION_ROLES

# Native desk workspaces when Loan Management / CRM modules are allowed (not LMS_NAV_SPEC).
ALLOWED_EXTRA_SIDEBAR_WORKSPACES = frozenset({"Loans", "Loan Management", "CRM"})


ROLE_USERS = {
	"LMS Admin": "demo.lms.admin@example.com",
	"LMS Branch Manager": "demo.lms.branch@example.com",
	"LMS Loan Officer": "demo.lms.officer@example.com",
	"LMS Collector": "demo.lms.collector@example.com",
}


def run_all():
	"""Entry point for bench execute."""
	audit = audit_all_roles()
	desk = audit_desk_api()
	crm = audit_crm_role_permissions()
	audit["desk_api"] = desk
	audit["crm_permissions"] = crm
	audit["ok"] = audit.get("ok") and desk.get("ok", False) and crm.get("ok", False)
	return audit


# Expected desk email / CRM capabilities per LMS role (Custom DocPerm + has_permission).
_CRM_PERM_MATRIX = {
	"LMS Admin": {
		"Lead": {"read": 1, "email": 1, "delete": 1},
		"Email Account": {"read": 1},
		"Customer": {"email": 1},
		"Territory": {"read": 1},
	},
	"LMS Branch Manager": {
		"Lead": {"read": 1, "email": 1, "delete": 1},
		"Email Account": {"read": 1},
		"Customer": {"email": 1},
		"Opportunity": {"read": 1, "email": 1},
	},
	"LMS Loan Officer": {
		"Lead": {"read": 1, "email": 1},
		"Email Account": {"read": 1},
		"Email Template": {"read": 1},
		"Customer": {"email": 1},
		"Communication": {"read": 1, "email": 1},
		"Lead Source": {"read": 1},
	},
	"LMS Collector": {
		"Lead": {"read": 0},
		"Opportunity": {"read": 0},
		"Email Account": {"read": 1},
		"Customer": {"email": 1},
		"Communication": {"read": 1, "email": 1},
	},
}


def audit_crm_role_permissions():
	"""Verify CRM + desk email Custom DocPerm rows match the role matrix."""
	results = {"ok": True, "roles": {}}

	for role, expectations in _CRM_PERM_MATRIX.items():
		email = ROLE_USERS.get(role)
		if not email or not frappe.db.exists("User", email):
			results["roles"][role] = {"ok": False, "error": "demo user missing"}
			results["ok"] = False
			continue

		checks = {}
		role_ok = True
		for doctype, fields in expectations.items():
			if fields.get("read") == 0:
				ok, detail = _cannot_read_doctype(email, doctype)
				checks[doctype] = {"ok": ok, "expect": "no read", "detail": detail}
			else:
				ok, detail = _docperm_matches(email, doctype, fields)
				checks[doctype] = {"ok": ok, "expect": fields, "detail": detail}
			if not checks[doctype]["ok"]:
				role_ok = False

		# Origination roles should run at least one CRM workspace report when installed.
		if role in ORIGINATION_ROLES and frappe.db.exists("Report", "Lead Details"):
			report_ok, report_detail = _can_read_report(email, "Lead Details")
			checks["Lead Details"] = {"ok": report_ok, "detail": report_detail}
			if not report_ok:
				role_ok = False

		results["roles"][role] = {"ok": role_ok, "email": email, "checks": checks}
		if not role_ok:
			results["ok"] = False

	return results


def _docperm_matches(user: str, doctype: str, expected: dict):
	try:
		frappe.set_user(user)
		for ptype, want in expected.items():
			if ptype == "delete" and want:
				if not frappe.has_permission(doctype, ptype="delete"):
					return False, f"missing delete on {doctype}"
				continue
			if not frappe.has_permission(doctype, ptype=ptype):
				return False, f"missing {ptype} on {doctype}"
		return True, doctype
	except frappe.PermissionError as exc:
		return False, str(exc)
	except Exception as exc:
		return False, str(exc)
	finally:
		frappe.set_user("Administrator")


def _cannot_read_doctype(user: str, doctype: str):
	try:
		frappe.set_user(user)
		if frappe.has_permission(doctype, ptype="read"):
			return False, f"unexpected read on {doctype}"
		return True, f"no read on {doctype}"
	except frappe.PermissionError:
		return True, f"no read on {doctype}"
	except Exception as exc:
		return False, str(exc)
	finally:
		frappe.set_user("Administrator")


def audit_desk_api():
	"""Exercise Frappe desk sidebar + workspace load APIs as each demo user."""
	from frappe.desk.desktop import Workspace, get_workspace_sidebar_items

	results = {"ok": True, "users": {}}
	all_titles = [spec["title"] for spec in LMS_NAV_SPEC if not spec.get("hidden")]

	for role, email in ROLE_USERS.items():
		if not frappe.db.exists("User", email):
			continue
		roles = set(frappe.get_roles(email))
		allowed = {
			spec["title"]
			for spec in LMS_NAV_SPEC
			if not spec.get("hidden") and roles & set(spec.get("roles", ()))
		}

		frappe.set_user(email)
		try:
			sidebar = get_workspace_sidebar_items()
			sidebar_pages = sidebar.get("pages", [])
			sidebar_titles = {p.get("title") for p in sidebar_pages if p.get("title")}
			loads = {}
			for title in all_titles:
				if title not in allowed:
					loads[title] = {"ok": title not in sidebar_titles, "skipped": True}
					continue
				page = next((p for p in sidebar_pages if p.get("title") == title), None)
				if not page:
					loads[title] = {"ok": False, "error": "not in sidebar"}
					continue
				try:
					ws = Workspace(page)
					ws.build_workspace()
					loads[title] = {"ok": True, "shortcuts": len(ws.shortcuts or [])}
				except Exception as exc:
					loads[title] = {"ok": False, "error": str(exc)[:240]}

			missing = sorted(allowed - sidebar_titles)
			extra = sorted(sidebar_titles - allowed - ALLOWED_EXTRA_SIDEBAR_WORKSPACES)
			sidebar_ok = not missing and not extra
			load_ok = all(v.get("ok") for t, v in loads.items() if t in allowed)
			user_ok = sidebar_ok and load_ok
			results["users"][role] = {
				"ok": user_ok,
				"email": email,
				"expected_sidebar": sorted(allowed),
				"actual_sidebar": sorted(sidebar_titles),
				"missing_sidebar": missing,
				"extra_sidebar": extra,
				"workspace_loads": loads,
			}
			if not user_ok:
				results["ok"] = False
		finally:
			frappe.set_user("Administrator")

	return results


def audit_all_roles():
	results = {"ok": True, "roles": {}, "users_missing": []}

	for role, email in ROLE_USERS.items():
		if not frappe.db.exists("User", email):
			results["users_missing"].append({"role": role, "email": email})
			results["ok"] = False
			continue
		results["roles"][role] = audit_user(email, role)

	role_ok = all(r.get("ok") for r in results["roles"].values())
	results["ok"] = results["ok"] and role_ok and not results["users_missing"]
	return results


def audit_user(email: str, expected_role: str | None = None):
	roles = set(frappe.get_roles(email))
	workspaces = _visible_workspaces(roles)
	workspace_checks = {}
	access_ok = True

	for spec in LMS_NAV_SPEC:
		if spec.get("hidden"):
			continue
		title = spec["title"]
		allowed_roles = set(spec.get("roles", ()))
		should_see = bool(roles & allowed_roles)
		visible = title in workspaces
		route = _workspace_route(title)
		page_ok, page_detail = _can_read_workspace_page(email, title)

		item_ok = (should_see == visible) and (not should_see or page_ok)
		if not item_ok:
			access_ok = False

		shortcuts = {}
		if should_see and visible and page_ok:
			shortcuts = _check_shortcuts(email, spec)

		workspace_checks[title] = {
			"ok": item_ok and all(s.get("ok", True) for s in shortcuts.values()),
			"should_see": should_see,
			"visible": visible,
			"route": route,
			"page_access": page_ok,
			"page_detail": page_detail,
			"shortcuts": shortcuts,
		}
		if not workspace_checks[title]["ok"]:
			access_ok = False

		portal = _check_portal(email, roles)
		page_doctype_ok, page_doctype_detail = _can_read_doctype(email, "Page")

		return {
			"ok": access_ok and portal.get("ok", True) and page_doctype_ok,
			"email": email,
			"roles": sorted(roles),
			"expected_role": expected_role,
			"has_expected_role": (expected_role in roles) if expected_role else None,
			"page_doctype_access": page_doctype_ok,
			"page_doctype_detail": page_doctype_detail,
			"workspaces": workspace_checks,
			"portal": portal,
		}


def _visible_workspaces(user_roles: set[str]) -> set[str]:
	visible = set()
	for ws in frappe.get_all("Workspace", fields=["name", "public", "for_user"]):
		doc = frappe.get_doc("Workspace", ws.name)
		ws_roles = {r.role for r in (doc.roles or [])}
		if not ws_roles:
			continue
		if user_roles & ws_roles:
			visible.add(doc.title or doc.name)
	return visible


def _workspace_route(title: str) -> str | None:
	if not frappe.db.exists("Workspace", title):
		return None
	page = frappe.db.get_value("Workspace", title, "name")
	return f"/app/{frappe.scrub(page)}"


def _can_read_workspace_page(user: str, workspace_title: str):
	"""Workspace desk routes are backed by Page documents."""
	if not frappe.db.exists("Workspace", workspace_title):
		return False, "workspace missing"

	page_name = frappe.db.get_value("Workspace", workspace_title, "name")
	if not frappe.db.exists("Page", page_name):
		# Some sites resolve workspace without explicit Page — treat as ok if workspace exists.
		return True, "no page doc (workspace only)"

	try:
		frappe.set_user(user)
		frappe.has_permission("Page", ptype="read", doc=page_name, throw=True)
		return True, page_name
	except frappe.PermissionError:
		return False, f"no Page read: {page_name}"
	except Exception as exc:
		return False, str(exc)
	finally:
		frappe.set_user("Administrator")


def _check_shortcuts(user: str, spec: dict):
	out = {}
	for sc in spec.get("shortcuts", []):
		label = sc.get("label")
		link_type = sc.get("type")
		if link_type == "DocType":
			ok, detail = _can_read_doctype(user, sc.get("link_to"))
		elif link_type == "Report":
			ok, detail = _can_read_report(user, sc.get("link_to"))
		elif link_type == "URL":
			ok, detail = True, sc.get("url")
		else:
			ok, detail = True, "skipped"
		out[label] = {"ok": ok, "type": link_type, "detail": detail}
	return out


def _can_read_doctype(user: str, doctype: str | None):
	if not doctype:
		return False, "missing doctype"
	try:
		frappe.set_user(user)
		frappe.has_permission(doctype, ptype="read", throw=True)
		return True, doctype
	except frappe.PermissionError:
		return False, f"no read: {doctype}"
	except Exception as exc:
		return False, str(exc)
	finally:
		frappe.set_user("Administrator")


def _can_read_report(user: str, report: str | None):
	if not report:
		return False, "missing report"
	if not frappe.db.exists("Report", report):
		return False, "report missing"
	try:
		frappe.set_user(user)
		frappe.has_permission("Report", ptype="report", doc=report, throw=True)
		return True, report
	except frappe.PermissionError:
		return False, f"no report perm: {report}"
	except Exception as exc:
		return False, str(exc)
	finally:
		frappe.set_user("Administrator")


def _check_portal(user: str, roles: set[str]):
	if "Customer" not in roles:
		return {"ok": True, "skipped": True}

	try:
		frappe.set_user(user)
		from lms_saas.api import portal

		loans = portal.get_my_loans()
		return {"ok": True, "loan_count": len(loans or [])}
	except Exception as exc:
		return {"ok": False, "error": str(exc)}
	finally:
		frappe.set_user("Administrator")
