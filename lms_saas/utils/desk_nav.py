"""Desk navigation payload for LMS staff (boot session + route → workspace mapping)."""

from __future__ import annotations

import frappe
from frappe.desk.utils import slug

from lms_saas.install import ALL_LMS_ROLES, LMS_NAV_SPEC, _resolve_workspace_spec

LMS_DESK_ROLES = frozenset((*ALL_LMS_ROLES, "System Manager"))


def workspace_url(title: str) -> str:
	return f"/app/{slug(title)}"


def _roles_overlap(user_roles: set[str], required: tuple[str, ...]) -> bool:
	return bool(user_roles.intersection(required))


def _register_route(
	route_map: dict[str, str], route_key: str, workspace: str, *, is_landing: bool = False
) -> None:
	if not route_key or not workspace:
		return
	existing = route_map.get(route_key)
	if existing is None:
		route_map[route_key] = workspace
	elif not is_landing:
		# Child workspaces win over the landing hub for shared shortcuts.
		route_map[route_key] = workspace


def _register_shortcut(
	route_map: dict[str, str], shortcut: dict, workspace: str, *, is_landing: bool = False
) -> None:
	link_type = shortcut.get("type")
	link_to = (shortcut.get("link_to") or "").strip()
	if not link_to:
		return

	if link_type == "DocType":
		_register_route(route_map, f"List/{link_to}", workspace, is_landing=is_landing)
		_register_route(route_map, f"Form/{link_to}", workspace, is_landing=is_landing)
	elif link_type == "Report":
		_register_route(route_map, f"query-report/{link_to}", workspace, is_landing=is_landing)
		_register_route(route_map, f"Report/{link_to}", workspace, is_landing=is_landing)


def get_lms_desk_nav(user: str | None = None) -> dict:
	"""Return role-filtered workspace nav + route map for client-side highlighting."""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return {"enabled": False}

	user_roles = set(frappe.get_roles(user))
	if not user_roles.intersection(LMS_DESK_ROLES):
		return {"enabled": False}

	items: list[dict] = []
	route_map: dict[str, str] = {}

	for spec in sorted(LMS_NAV_SPEC, key=lambda row: row.get("sequence_id", 99)):
		spec = _resolve_workspace_spec(spec)
		if spec.get("hidden"):
			continue
		required_roles = spec.get("roles", ())
		if not _roles_overlap(user_roles, required_roles):
			continue

		title = spec["title"]
		is_landing = bool(spec.get("landing"))
		items.append(
			{
				"key": spec.get("key"),
				"title": title,
				"url": workspace_url(title),
				"route": f"Workspaces/{title}",
				"icon": spec.get("icon") or "folder",
				"parent": spec.get("parent"),
				"is_landing": is_landing,
			}
		)

		for shortcut in spec.get("shortcuts") or ():
			if shortcut.get("type") == "Report" and not frappe.db.exists("Report", shortcut.get("link_to")):
				continue
			_register_shortcut(route_map, shortcut, title, is_landing=is_landing)

		for card in spec.get("cards") or ():
			if not isinstance(card, dict):
				continue
			for link in card.get("links") or ():
				label, link_to, link_type, _is_query = link[:4]
				_register_shortcut(
					route_map,
					{"type": link_type, "link_to": link_to, "label": label},
					title,
					is_landing=is_landing,
				)

	return {
		"enabled": True,
		"use_native_lending": True,
		"home_url": "/app/loans",
		"items": items,
		"route_map": route_map,
	}
