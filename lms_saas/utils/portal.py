"""Borrower portal helpers — menu lockdown and website context."""

from __future__ import annotations

import frappe

from lms_saas.boot import LMS_DESK_ROLES

# ERPNext seeds these for Customer; LMS borrowers only need loan self-service.
ERPNext_CUSTOMER_PORTAL_ROUTES = (
	"/project",
	"/quotations",
	"/orders",
	"/invoices",
	"/shipments",
	"/issues",
	"/addresses",
	"/timesheets",
	"/material-requests",
	"/newsletters",
)

LMS_BORROWER_PORTAL_ROUTES = (
	"/lms",
	"/lms/account",
)

LEGACY_ACCOUNT_PATHS = (
	"me",
	"update-profile",
	"update-password",
	"third_party_apps",
)


def is_portal_borrower(user: str | None = None) -> bool:
	"""Website-only Customer (no desk / LMS staff roles)."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False

	roles = set(frappe.get_roles(user))
	if "Customer" not in roles:
		return False
	if roles & LMS_DESK_ROLES:
		return False
	if "Desk User" in roles:
		return False
	return True


def show_staff_desk_link(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return False
	roles = set(frappe.get_roles(user))
	return bool(roles & LMS_DESK_ROLES)


def prune_customer_portal_menu() -> dict:
	"""Disable ERPNext portal clutter; keep LMS borrower routes only."""
	disabled = 0
	settings = frappe.get_doc("Portal Settings", "Portal Settings")

	for row in settings.menu:
		if row.role != "Customer":
			continue
		if row.route in ERPNext_CUSTOMER_PORTAL_ROUTES:
			row.enabled = 0
			disabled += 1
		elif row.route in LMS_BORROWER_PORTAL_ROUTES:
			row.enabled = 1

	_ensure_portal_item(settings, "My Loans", "/lms", "Loan")
	_ensure_portal_item(settings, "My Account", "/lms/account", "User")

	settings.default_portal_home = "/lms"
	settings.flags.ignore_permissions = True
	settings.save(ignore_permissions=True)

	frappe.clear_cache()
	return {"disabled": disabled}


def _ensure_portal_item(settings, title: str, route: str, reference_doctype: str | None) -> None:
	for row in settings.menu:
		if row.route == route and row.role == "Customer":
			row.enabled = 1
			row.title = title
			if reference_doctype:
				row.reference_doctype = reference_doctype
			return

	row = {
		"title": title,
		"enabled": 1,
		"route": route,
		"role": "Customer",
	}
	if reference_doctype:
		row["reference_doctype"] = reference_doctype
	settings.append("menu", row)


def apply_borrower_web_context(context) -> None:
	"""Strip ERPNext portal chrome for website-only borrowers on legacy account pages."""
	if not is_portal_borrower():
		return

	path = (getattr(frappe.local, "path", None) or "").strip("/")
	if not path:
		path = (getattr(context, "pathname", None) or context.get("pathname") or context.get("path") or "").strip("/")

	is_legacy = any(path == legacy or path.startswith(f"{legacy}/") for legacy in LEGACY_ACCOUNT_PATHS)
	if not is_legacy and not path.startswith("lms"):
		return

	context.show_sidebar = False
	context.no_header = True
	body = (context.get("body_class") if isinstance(context, dict) else getattr(context, "body_class", None)) or ""
	merged = f"{body} lms-portal lms-portal-borrower lms-themed lms-portal-legacy".strip()
	if isinstance(context, dict):
		context["body_class"] = merged
		context["lms_portal_legacy"] = True
	else:
		context.body_class = merged
		context.lms_portal_legacy = True
