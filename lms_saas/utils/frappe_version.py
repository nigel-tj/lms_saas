"""Frappe major-version helpers (v15 /app vs v16 /desk routing)."""

from __future__ import annotations


def get_major_version() -> int:
	import frappe

	version = getattr(frappe, "__version__", "0.0.0") or "0.0.0"
	try:
		return int(str(version).split(".", maxsplit=1)[0])
	except (TypeError, ValueError):
		return 0


def is_v16_or_later() -> bool:
	return get_major_version() >= 16


def desk_prefix() -> str:
	return "/desk" if is_v16_or_later() else "/app"


def desk_url(path: str = "") -> str:
	"""Build a desk path for the active Frappe major version."""
	path = (path or "").strip()
	if not path:
		return desk_prefix()
	if path.startswith("http://") or path.startswith("https://"):
		return path
	for legacy in ("/app/", "/desk/"):
		if path.startswith(legacy):
			path = path[len(legacy) :]
			break
	path = path.lstrip("/")
	return f"{desk_prefix()}/{path}" if path else desk_prefix()


def rewrite_desk_path(path: str) -> str:
	"""Normalize legacy /app/… or bare paths to the current desk prefix."""
	return desk_url(path)


# Native Frappe Lending module workspace (slug "lending", not "loans").
LENDING_HOME_SLUG = "lending"


def lending_home_url() -> str:
	"""Staff desk home — native Lending workspace."""
	return desk_url(LENDING_HOME_SLUG)
