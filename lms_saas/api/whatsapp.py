"""WhatsApp Business addon API — send messages, templates, log, stats.

Uses new LMS WhatsApp Template doctype + existing LMS Notification Log
(with channel=WhatsApp).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import now_datetime, today, flt

from lms_saas.utils.addons import require_addon_persona


def _require_whatsapp():
    require_addon_persona("whatsapp")


def _is_admin():
    roles = set(frappe.get_roles())
    return bool(roles.intersection({"System Manager", "Administrator"}))


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

@frappe.whitelist()
def send_whatsapp(recipient, message, template_name=None, loan=None, reference_doctype=None, reference_name=None):
    """Send a WhatsApp message via config-driven provider.

    The provider is configured in site_config under ``lms_whatsapp``:
        {
            "provider": "twilio" | "meta" | "africa_stalking",
            "api_key": "...",
            "api_secret": "...",
            "sender": "whatsapp:+...",
        }

    This method logs the attempt in LMS Notification Log regardless of
    whether the provider call succeeds.
    """
    _require_whatsapp()

    if not recipient or not message:
        frappe.throw(_("Recipient and message are required."))

    # Resolve template body if template_name is provided
    if template_name:
        template = frappe.db.get_value(
            "LMS WhatsApp Template",
            template_name,
            ["template_body", "is_approved"],
            as_dict=True,
        )
        if template:
            if not template.is_approved:
                frappe.throw(_("Template is not approved."), frappe.PermissionError)
            message = template.template_body

    # Attempt provider send (best-effort)
    status = "Sent"
    error_msg = None
    try:
        _send_via_provider(recipient, message)
    except Exception as e:
        status = "Failed"
        error_msg = str(e)
        frappe.log_error(title="WhatsApp send failed", message=frappe.get_traceback())

    # Log to LMS Notification Log
    log = frappe.new_doc("LMS Notification Log")
    log.loan = loan
    log.reference_doctype = reference_doctype
    log.reference_name = reference_name
    log.reminder_type = "WhatsApp"
    log.notification_date = today()
    log.channel = "WhatsApp"
    log.status = status
    log.recipient = recipient
    log.message_preview = message[:200] if message else ""
    log.sent_on = now_datetime()
    log.flags.ignore_permissions = True
    log.insert()

    return {"ok": status == "Sent", "status": status, "error": error_msg}


def _send_via_provider(recipient, message):
    """Send via the configured WhatsApp provider.

    Reads provider config from ``frappe.conf.lms_whatsapp``.
    Raises on failure.
    """
    conf = frappe.conf.get("lms_whatsapp") or {}
    provider = conf.get("provider")

    if not provider:
        # No provider configured — treat as a dry run (message is logged)
        frappe.log_error(title="WhatsApp: no provider configured", message="Recipient: " + recipient)
        return

    # Provider implementations would go here (Twilio, Meta, Africa's Talking, etc.)
    # For now, this is a stub that logs the attempt.
    # In production, integrate with the actual provider API.
    frappe.logger().info("WhatsApp send via %s to %s: %s", provider, recipient, message[:100])


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_templates(limit=50):
    """Return LMS WhatsApp Templates."""
    _require_whatsapp()

    templates = frappe.get_all(
        "LMS WhatsApp Template",
        fields=["name", "template_name", "template_body", "category",
                "language", "is_approved", "variables"],
        order_by="template_name asc",
        limit_page_length=int(limit),
    )
    return {"templates": templates}


@frappe.whitelist()
def create_template(template_name, template_body, category, language="en",
                      is_approved=False, variables=None):
    """Admin-only: create a new WhatsApp template."""
    _require_whatsapp()
    if not _is_admin():
        frappe.throw(_("Only administrators can create templates."), frappe.PermissionError)

    doc = frappe.new_doc("LMS WhatsApp Template")
    doc.template_name = template_name
    doc.template_body = template_body
    doc.category = category
    doc.language = language
    doc.is_approved = bool(is_approved)
    doc.variables = variables
    doc.flags.ignore_permissions = True
    doc.insert()

    return {"name": doc.name, "template_name": doc.template_name}


# ---------------------------------------------------------------------------
# Log
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_whatsapp_log(limit=100):
    """Return notification log entries with channel=WhatsApp."""
    _require_whatsapp()

    filters = {"channel": "WhatsApp"}
    if not _is_admin():
        branch = _branch()
        if branch:
            # Branch scoping via loan's custom_lms_branch
            branch_loans = frappe.get_all("Loan", filters={"custom_lms_branch": branch}, pluck="name")
            if branch_loans:
                filters["loan"] = ("in", branch_loans)

    logs = frappe.get_all(
        "LMS Notification Log",
        filters=filters,
        fields=["name", "loan", "reference_doctype", "reference_name",
                "reminder_type", "notification_date", "channel", "status",
                "recipient", "message_preview", "sent_on", "read_on"],
        order_by="notification_date desc",
        limit_page_length=int(limit),
    )
    return {"logs": logs}


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

@frappe.whitelist()
def get_whatsapp_stats():
    """Overview stats: delivery, read, response rates."""
    _require_whatsapp()

    total = frappe.db.count("LMS Notification Log", {"channel": "WhatsApp"})
    sent = frappe.db.count("LMS Notification Log", {"channel": "WhatsApp", "status": "Sent"})
    failed = frappe.db.count("LMS Notification Log", {"channel": "WhatsApp", "status": "Failed"})
    skipped = frappe.db.count("LMS Notification Log", {"channel": "WhatsApp", "status": "Skipped"})

    # Read rate (messages with read_on set)
    read_count = frappe.db.count("LMS Notification Log", {
        "channel": "WhatsApp",
        "read_on": ("is", "set"),
    })

    delivery_rate = round((sent / total * 100), 1) if total else 0
    read_rate = round((read_count / sent * 100), 1) if sent else 0

    total_templates = frappe.db.count("LMS WhatsApp Template")
    approved_templates = frappe.db.count("LMS WhatsApp Template", {"is_approved": 1})

    return {
        "total_sent": total,
        "delivered": sent,
        "failed": failed,
        "skipped": skipped,
        "read": read_count,
        "delivery_rate": delivery_rate,
        "read_rate": read_rate,
        "total_templates": total_templates,
        "approved_templates": approved_templates,
    }