"""WhatsApp Business addon API — send messages, templates, log, stats.

Uses new LMS WhatsApp Template doctype + existing LMS Notification Log
(with channel=WhatsApp).
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import now_datetime, today, flt

from lms_saas.utils.addons import require_addon_persona


def _require_whatsapp():
    require_addon_persona("whatsapp")


def _is_admin():
    from lms_saas.utils.access_control import is_admin
    return is_admin()


def _branch():
    from lms_saas.api.staff import get_current_user_branch
    return get_current_user_branch()


# ---------------------------------------------------------------------------
# Send
# ---------------------------------------------------------------------------

@frappe.whitelist()
@rate_limit(limit=20, seconds=60, methods=["POST"])
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

    Reads provider config from ``frappe.conf.lms_whatsapp``:
        {
            "provider": "twilio" | "meta" | "africa_stalking",
            "api_key": "...",
            "api_secret": "...",       # Twilio auth_token / Meta app secret
            "account_sid": "...",      # Twilio only
            "phone_number_id": "...",  # Meta only
            "sender": "whatsapp:+...", # Twilio / Africa's Talking
            "from": "...",             # Meta sender ID
        }

    Raises on failure so the caller can catch and log to the
    Notification Log with status='Failed'.
    """
    import requests

    conf = frappe.conf.get("lms_whatsapp") or {}
    provider = conf.get("provider")

    if not provider:
        # No provider configured — treat as a dry run (message is logged)
        frappe.log_error(title="WhatsApp: no provider configured", message="Recipient: " + recipient)
        return

    sender = conf.get("sender") or conf.get("from") or ""
    api_key = conf.get("api_key") or ""
    api_secret = conf.get("api_secret") or ""

    if provider == "twilio":
        _send_via_twilio(recipient, message, conf, sender, api_key, api_secret, requests)
    elif provider == "meta":
        _send_via_meta(recipient, message, conf, sender, api_key, api_secret, requests)
    elif provider == "africa_stalking":
        _send_via_africas_talking(recipient, message, conf, sender, api_key, api_secret, requests)
    else:
        frappe.throw(_("Unknown WhatsApp provider: {0}").format(provider))

    frappe.logger().info("WhatsApp send via %s to %s: %s", provider, recipient, message[:100])


def _send_via_twilio(recipient, message, conf, sender, api_key, api_secret, requests):
    """Send WhatsApp via Twilio's WhatsApp API.

    Uses the same Messages endpoint as SMS, but the From/To numbers
    must be prefixed with ``whatsapp:``.
    """
    account_sid = conf.get("account_sid") or api_key
    if not account_sid or not api_secret:
        frappe.throw(_("Twilio WhatsApp: account_sid and api_secret are required."))

    from_number = sender if sender.startswith("whatsapp:") else f"whatsapp:{sender}"
    to_number = recipient if recipient.startswith("whatsapp:") else f"whatsapp:{recipient}"

    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    resp = requests.post(
        url,
        auth=(account_sid, api_secret),
        data={"To": to_number, "From": from_number, "Body": message},
        timeout=15,
    )
    if resp.status_code >= 300:
        frappe.throw(
            _("Twilio WhatsApp send failed (HTTP {0}): {1}").format(
                resp.status_code, resp.text[:500]
            )
        )


def _send_via_meta(recipient, message, conf, sender, api_key, api_secret, requests):
    """Send WhatsApp via Meta Cloud API.

    ``api_key`` is the access token, ``conf.phone_number_id`` is the
    Meta phone number ID. The recipient must be a bare international
    number (no ``whatsapp:`` prefix).
    """
    phone_number_id = conf.get("phone_number_id")
    if not phone_number_id or not api_key:
        frappe.throw(_("Meta WhatsApp: phone_number_id and api_key are required."))

    # Strip whatsapp: prefix if present — Meta wants bare numbers.
    to_number = recipient.replace("whatsapp:", "")

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if resp.status_code >= 300:
        frappe.throw(
            _("Meta WhatsApp send failed (HTTP {0}): {1}").format(
                resp.status_code, resp.text[:500]
            )
        )


def _send_via_africas_talking(recipient, message, conf, sender, api_key, api_secret, requests):
    """Send WhatsApp via Africa's Talking.

    ``api_key`` is the AT API key, ``sender`` is the short code or
    alphanumeric sender ID.
    """
    if not api_key:
        frappe.throw(_("Africa's Talking WhatsApp: api_key is required."))

    # AT expects bare international numbers.
    to_number = recipient.replace("whatsapp:", "")

    url = "https://api.africastalking.com/version1/messaging"
    headers = {
        "apiKey": api_key,
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    payload = {
        "username": conf.get("username") or "",
        "to": to_number,
        "message": message,
        "from": sender,
        "bulkSMSMode": "0",
    }
    resp = requests.post(url, headers=headers, data=payload, timeout=15)
    if resp.status_code >= 300:
        frappe.throw(
            _("Africa's Talking WhatsApp send failed (HTTP {0}): {1}").format(
                resp.status_code, resp.text[:500]
            )
        )


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