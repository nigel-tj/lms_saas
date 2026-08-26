"""LMS Setup Change Request — R52 compliance anchor.

This doctype stores proposed Tier A changes (Loan Product, LMS Credit Policy)
made by the Operations Manager persona. It is the single server-side evidence
entry for every Tier A change:

  - ``proposed_fields`` (JSON): the requested field → value map.
  - ``old_values`` (JSON): a snapshot of the live doc's state at the time the
    change was proposed. Used to render the diff in the portal Change Requests
    tab + the regulator's evidence pack.
  - ``status`` lifecycle: Pending → (Approved | Rejected | Pending — Missing GL
    Accounts) → (Applied | Cancelled).
  - ``audit_event_ref``: the LMS Audit Event row written on apply (the
    tamper-evident timestamp).

Tickets 2 and 3 extend this controller with the apply logic for the two
target doctypes. This file is intentionally minimal — it provides the
doctype + lifecycle + a few helpers shared by the apply paths.
"""

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.model.document import Document


# Status values mirror the Select options in the doctype JSON.
STATUS_PENDING = "Pending"
STATUS_PENDING_GL_MISSING = "Pending — Missing GL Accounts"
STATUS_APPROVED = "Approved"
STATUS_REJECTED = "Rejected"
STATUS_APPLIED = "Applied"
STATUS_CANCELLED = "Cancelled"


class LMSSetupChangeRequest(Document):
    """Compliance anchor for Tier A setup changes.

    The controller deliberately exposes very little — the actual proposal /
    approval / apply logic lives in :mod:`lms_saas.api.setup` so that the
    guard can run *before* any doc events fire (the lending-app controllers
    on the target doctypes have their own perms we don't want to trigger).
    """

    # ------------------------------------------------------------------
    # Standard hooks — keep the lifecycle rows in good shape.
    # ------------------------------------------------------------------

    def before_insert(self):
        """Stamp requested_by + requested_at on first save."""
        if not self.requested_by:
            self.requested_by = frappe.session.user
        if not self.requested_at:
            self.requested_at = frappe.utils.now_datetime()

        # JSON fields arrive as strings from the portal; parse once on insert
        # so downstream code can read .get_proposed_fields() safely.
        if isinstance(self.proposed_fields, str) and self.proposed_fields.strip():
            try:
                json.loads(self.proposed_fields)
            except json.JSONDecodeError as e:
                frappe.throw(f"proposed_fields is not valid JSON: {e}")
        if isinstance(self.old_values, str) and self.old_values.strip():
            try:
                json.loads(self.old_values)
            except json.JSONDecodeError as e:
                frappe.throw(f"old_values is not valid JSON: {e}")

    def validate(self):
        """Status must be one of the allowed values; cross-field sanity checks."""
        allowed = {
            STATUS_PENDING,
            STATUS_PENDING_GL_MISSING,
            STATUS_APPROVED,
            STATUS_REJECTED,
            STATUS_APPLIED,
            STATUS_CANCELLED,
        }
        if self.status not in allowed:
            frappe.throw(
                f"Invalid status {self.status!r}. Allowed: {sorted(allowed)}"
            )

        # Target name is set on apply for Create; on Edit/Disable the
        # proposer must already know which doc to mutate.
        if self.change_type in ("Edit", "Disable") and not self.target_name:
            frappe.throw(
                "target_name is required when change_type is Edit or Disable."
            )

    # ------------------------------------------------------------------
    # Convenience accessors — Ticket 2 + 3 apply paths use these.
    # ------------------------------------------------------------------

    def get_proposed_fields(self) -> dict[str, Any]:
        """Return ``proposed_fields`` as a parsed dict (or empty dict)."""
        if not self.proposed_fields:
            return {}
        if isinstance(self.proposed_fields, dict):
            return self.proposed_fields
        try:
            return json.loads(self.proposed_fields)
        except (json.JSONDecodeError, TypeError):
            return {}

    def get_old_values(self) -> dict[str, Any]:
        """Return ``old_values`` as a parsed dict (or empty dict)."""
        if not self.old_values:
            return {}
        if isinstance(self.old_values, dict):
            return self.old_values
        try:
            return json.loads(self.old_values)
        except (json.JSONDecodeError, TypeError):
            return {}

    def is_terminal(self) -> bool:
        """Return True if no further state transitions are allowed."""
        return self.status in (STATUS_APPLIED, STATUS_REJECTED, STATUS_CANCELLED)
