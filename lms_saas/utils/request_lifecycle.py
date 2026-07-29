"""Per-request security flags lifecycle.

R20-L1: ``frappe.flags.ignore_permissions`` was being set globally by
``_require_officer`` / ``_require_manager`` without being restored, so any
later endpoint in the same request lifecycle inherited the bypass. The fix
hooks into Frappe's ``after_request`` cycle and clears the flag once the
request is served.

Use the ``ignore_permissions`` context manager in :mod:`lms_saas.utils.rate_limit`
for code paths that need the bypass for a narrow block AND need it restored
deterministically (e.g. callbacks that may raise).
"""

from __future__ import annotations

import frappe


def reset_permission_flags():
	"""R20-L1: clear transient security flags at end of request.

	Called from the ``after_request`` hook declared in ``hooks.py``. Clearing
	``ignore_permissions`` prevents a leaked bypass from carrying into a
	later endpoint within the same request.
	"""
	try:
		frappe.flags.ignore_permissions = False
	except Exception:
		pass