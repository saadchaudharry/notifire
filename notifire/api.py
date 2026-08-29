# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""The webhook endpoint.

    POST /api/method/notifire.api.webhook?group=<name>
    Header: X-Webhook-Secret: <bench group token, or the global secret>

Guest-accessible because Frappe Cloud is not a Desk user; every request is
authenticated by hand against the token.
"""

import secrets

import frappe
from frappe import _

from notifire import utils


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook(group=None):
    request = frappe.local.request
    provided = request.headers.get("X-Webhook-Secret", "") or ""
    raw_body = request.get_data(as_text=True) or ""

    doc = _authenticate(group, provided)

    payload, error = utils.parse_payload(raw_body)
    if error:
        frappe.throw(_(error), frappe.ValidationError)

    event = payload["event"].strip()

    # Frappe Cloud sends this when you press Validate Webhook. Answer OK and
    # log it, but do not email anyone.
    if event == "Webhook Validate":
        utils.create_log(event, None, payload, doc.name, [], "Received", "Webhook validated")
        return "OK"

    utils.process_event(event, payload, group=doc.name)
    return "OK"


def _authenticate(group, provided):
    """Return the enabled Bench Group, or raise 401.

    An unknown group and a bad token give the same answer on purpose, so
    nobody can probe for valid group names.
    """
    doc = None
    if group and isinstance(group, str):
        name = frappe.db.get_value("Bench Group", group.strip(), ["name", "enabled"], as_dict=True)
        if name and name.enabled:
            doc = frappe.get_doc("Bench Group", name.name)

    global_secret = utils.settings().webhook_secret or ""
    token = doc.token if doc else ""

    if not doc or not utils.valid_secret(provided, token, global_secret):
        frappe.throw(_("Unauthorized"), frappe.AuthenticationError)
    return doc


@frappe.whitelist(methods=["POST"])
def regenerate_token(group):
    """Replace a group's token. The old one stops working immediately."""
    doc = frappe.get_doc("Bench Group", group)
    doc.check_permission("write")
    doc.token = secrets.token_hex(24)
    doc.save()
    return {"token": doc.token}
