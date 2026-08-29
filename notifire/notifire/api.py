# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Webhook receiver endpoint + small Desk helper methods.

    POST /api/method/notifire.api.webhook?group=<slug>
    Header: X-Webhook-Secret: <per-group secret or global fallback secret>

Guest-accessible by design (webhook senders are not Desk users); every
request is authenticated manually with constant-time secret comparison.
"""

import secrets

import frappe
from frappe import _

from notifire.notifire import utils

SECRET_HEADER = "X-Webhook-Secret"


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook(group=None):
    """Frappe Cloud webhook receiver.

    Both the group slug and the payload secret are required. Flow:
    authenticate -> parse JSON -> validate event -> Webhook Validate
    shortcut (200 "OK", no email) -> process event -> respond JSON.
    """
    request = getattr(frappe.local, "request", None)
    raw_body = ""
    provided_secret = ""
    if request is not None:
        raw_body = request.get_data(cache=True, as_text=True) or ""
        provided_secret = request.headers.get(SECRET_HEADER, "") or ""
    return handle_webhook(group=group, provided_secret=provided_secret, raw_body=raw_body)


def handle_webhook(group, provided_secret, raw_body):
    """Process a webhook request. Kept request-independent for tests."""
    group_doc = _get_enabled_group(group)
    global_secret = utils.global_webhook_secret()

    if group_doc is None:
        # Unknown/disabled endpoints require the global secret before a
        # 404 is revealed (no free slug enumeration for strangers).
        if not utils.is_valid_secret(provided_secret, global_secret=global_secret):
            frappe.throw(_("Unauthorized"), frappe.AuthenticationError)
        frappe.throw(_("Unknown webhook endpoint"), frappe.DoesNotExistError)

    # Accepts the global fallback secret or this endpoint's own key.
    group_secret = group_doc.get_password("secret", raise_exception=False) or ""
    if not utils.is_valid_secret(provided_secret, group_secret=group_secret, global_secret=global_secret):
        frappe.throw(_("Unauthorized"), frappe.AuthenticationError)

    payload, parse_error = utils.parse_webhook_payload(raw_body)
    if payload is None:
        frappe.throw(_("Invalid webhook payload"), frappe.ValidationError)

    event = payload.get("event")
    if not isinstance(event, str) or not event.strip():
        frappe.throw(_("Invalid webhook payload"), frappe.ValidationError)
    event = event.strip()

    # --- Webhook Validate: acknowledge, no email, no error -------------
    if event == "Webhook Validate":
        utils.create_log(
            event=event,
            site=None,
            ref_name="",
            payload=payload,
            group=group_doc.name,
            recipients=[],
            status="Received",
            error="Webhook validation OK - no notification sent",
        )
        return "OK"

    # --- Process event (notify + log) ----------------------------------
    result = utils.process_webhook_event(event, payload)
    return {
        "status": "ok",
        "event": event,
        "notification_status": result["notification_status"],
    }


def _get_enabled_group(name):
    """Enabled Notifire Group by slug (docname == slug), else None."""
    if not name or not isinstance(name, str):
        return None
    group_name = frappe.db.get_value("Notifire Group", name.strip())
    if not group_name:
        return None
    doc = frappe.get_doc("Notifire Group", group_name)
    if not doc.enabled:
        return None
    return doc


@frappe.whitelist(methods=["POST"])
def rotate_group_secret(group: str):
    """Desk helper: replace a group's webhook secret (old one dies now)."""
    doc = frappe.get_doc("Notifire Group", group)
    doc.check_permission("write")
    doc.secret = secrets.token_hex(24)
    doc.save()
    return {"secret": doc.get_password("secret")}
