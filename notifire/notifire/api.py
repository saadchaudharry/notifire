# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Webhook receiver endpoint + the Desk helper methods the forms call.

    POST /api/method/notifire.api.webhook?group=<slug>
    Header: X-Webhook-Secret: <per-group secret or global fallback secret>

The receiver is guest-accessible by design (webhook senders are not Desk
users); every request is authenticated manually with a constant-time secret
comparison. Everything below the receiver is Desk-only and permission
checked.
External Frappe Cloud event
          │
          ▼
POST /api/method/notifire.api.webhook?group=my-group
          │
          ▼
Check X-Webhook-Secret
          │
          ├── invalid → Unauthorized
          │
          ▼
Parse JSON payload
          │
          ├── invalid → Validation error
          │
          ▼
Read "event"
          │
          ├── "Webhook Validate" → return "OK"
          │
          ▼
process_webhook_event(...)
          │
          ▼
Find recipients
          │
          ▼
Send email
          │
          ▼
Create notification/log
"""

import re
import secrets

import frappe
from frappe import _

from notifire.notifire import utils

SECRET_HEADER = "X-Webhook-Secret"


# ---------------------------------------------------------------------------
# Webhook receiver
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Desk helpers: group form
# ---------------------------------------------------------------------------

def webhook_url(slug):
    # Slugs are restricted to [a-z0-9-] by the group controller, so they are
    # already URL-safe.
    return "{}/api/method/notifire.api.webhook?group={}".format(
        frappe.utils.get_url().rstrip("/"), slug or ""
    )


@frappe.whitelist()
def group_overview(group):
    """Everything the group / recipient / site forms need, in one call.

    Returning one consistent snapshot is what keeps the three panels of the
    group form from contradicting each other.
    """
    doc = frappe.get_doc("Notifire Group", group)
    doc.check_permission("read")

    sites = frappe.get_all(
        "Notifire Site",
        filters={"group": doc.name},
        fields=["name as hostname", "label", "enabled"],
        order_by="name asc",
    )

    recipients = frappe.get_all(
        "Notifire Recipient",
        filters={"group": doc.name},
        fields=["name", "email", "enabled", "scope_mode"],
        order_by="email asc",
    )
    scopes = {}
    if recipients:
        for row in frappe.get_all(
            "Notifire Recipient Scope",
            filters={
                "parenttype": "Notifire Recipient",
                "parent": ("in", [r.name for r in recipients]),
            },
            fields=["parent", "hostname"],
        ):
            scopes.setdefault(row.parent, []).append(row.hostname)

    for rec in recipients:
        rec["applies_to"] = sorted(scopes.get(rec.name, []))

    defaults = [r.email for r in recipients if r.enabled and not r["applies_to"]]

    for site in sites:
        scoped = [
            r.email for r in recipients if r.enabled and site.hostname in r["applies_to"]
        ]
        if scoped:
            site["recipients"] = scoped
            site["source"] = "scoped"
        elif defaults:
            site["recipients"] = defaults
            site["source"] = "default"
        else:
            site["recipients"] = []
            site["source"] = "none"

    warnings = []
    if not recipients:
        warnings.append(
            _("No recipients yet - events for this group are logged as Failed until you add one.")
        )
    elif not defaults and any(s["source"] == "none" for s in sites):
        warnings.append(
            _("Some hostnames have no recipients. Add a default recipient to cover them.")
        )
    if not sites and not doc.fallback:
        warnings.append(
            _("No hostnames are mapped to this group, so nothing routes here yet.")
        )
    if not doc.enabled:
        warnings.append(_("This group is disabled: its endpoint answers as if it did not exist."))

    return {
        "group": {
            "name": doc.name,
            "title": doc.title,
            "slug": doc.slug,
            "enabled": bool(doc.enabled),
            "fallback": bool(doc.fallback),
        },
        "webhook_url": webhook_url(doc.slug),
        "sites": sites,
        "recipients": recipients,
        "defaults": defaults,
        "warnings": warnings,
    }


def _clean_hostname(raw):
    """Turn whatever was pasted into a bare lowercase hostname."""
    value = (raw or "").strip().lower()
    value = re.sub(r"^[a-z][a-z0-9+.-]*://", "", value)  # scheme
    value = value.split("/")[0].split("?")[0]  # path / query
    value = value.split("@")[-1]  # user@host
    value = value.split(":")[0]  # port
    return value.strip().strip(".,;\"'")


@frappe.whitelist(methods=["POST"])
def add_hostnames(group, hostnames, label=None, move_existing=0):
    """Map a pasted list of hostnames to a group in one go.

    Returns what happened to every entry instead of failing on the first
    bad one, because the usual input is a copy-pasted list of sites and
    losing the whole batch to one typo is miserable.
    """
    doc = frappe.get_doc("Notifire Group", group)
    doc.check_permission("write")

    move_existing = frappe.utils.cint(move_existing)
    label = (label or "").strip()

    added, moved, skipped = [], [], []
    seen = set()

    for raw in re.split(r"[\s,;]+", hostnames or ""):
        hostname = _clean_hostname(raw)
        if not hostname or hostname in seen:
            continue
        seen.add(hostname)

        if not utils.looks_like_hostname(hostname):
            skipped.append({"hostname": raw.strip()[:80], "reason": _("Not a valid hostname")})
            continue

        owner = frappe.db.get_value("Notifire Site", hostname, "group")
        if owner == doc.name:
            skipped.append({"hostname": hostname, "reason": _("Already mapped to this group")})
            continue
        if owner:
            if not move_existing:
                skipped.append(
                    {"hostname": hostname, "reason": _("Mapped to group {0}").format(owner)}
                )
                continue
            site = frappe.get_doc("Notifire Site", hostname)
            site.group = doc.name
            if label:
                site.label = label
            site.save()
            moved.append(hostname)
            continue

        frappe.get_doc(
            {
                "doctype": "Notifire Site",
                "hostname": hostname,
                "group": doc.name,
                "label": label,
                "enabled": 1,
            }
        ).insert()
        added.append(hostname)

    utils.update_site_count(doc.name)
    return {"added": added, "moved": moved, "skipped": skipped}


@frappe.whitelist(methods=["POST"])
def remove_hostname(group, hostname):
    """Unmap a hostname. Recipient scopes pointing at it are cleaned up."""
    doc = frappe.get_doc("Notifire Group", group)
    doc.check_permission("write")

    hostname = (hostname or "").strip().lower()
    site = frappe.db.get_value("Notifire Site", hostname, ["name", "group"], as_dict=True)
    if not site or site.group != doc.name:
        frappe.throw(_("{0} is not mapped to this group.").format(hostname))

    frappe.delete_doc("Notifire Site", site.name, delete_permanently=True)
    utils.update_site_count(doc.name)
    return {"removed": hostname}


@frappe.whitelist()
def get_group_secret(group):
    """Reveal a group's webhook secret to someone who could rotate it anyway."""
    doc = frappe.get_doc("Notifire Group", group)
    doc.check_permission("write")
    return {"secret": doc.get_password("secret", raise_exception=False) or ""}


@frappe.whitelist(methods=["POST"])
def rotate_group_secret(group):
    """Replace a group's webhook secret (the old one dies immediately)."""
    doc = frappe.get_doc("Notifire Group", group)
    doc.check_permission("write")
    doc.secret = secrets.token_hex(24)
    doc.save()
    return {"secret": doc.get_password("secret")}


# ---------------------------------------------------------------------------
# Desk helpers: settings + logs
# ---------------------------------------------------------------------------

@frappe.whitelist()
def settings_overview():
    """Counters and setup problems for the Notifire Settings health panel."""
    frappe.has_permission("Notifire Settings", "read", throw=True)

    since = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-24)
    counts = {
        "groups": frappe.db.count("Notifire Group", {"enabled": 1}),
        "sites": frappe.db.count("Notifire Site", {"enabled": 1}),
        "recipients": frappe.db.count("Notifire Recipient", {"enabled": 1}),
        "sent_24h": frappe.db.count("Notifire Log", {"status": "Sent", "creation": (">", since)}),
        "failed_24h": frappe.db.count("Notifire Log", {"status": "Failed", "creation": (">", since)}),
    }

    problems = []
    if not frappe.db.get_single_value("Notifire Settings", "enabled"):
        problems.append(_("Email notifications are turned off."))
    if not counts["groups"]:
        problems.append(_("No enabled notification group yet."))
    if not counts["recipients"]:
        problems.append(_("No enabled recipients yet - notifications will be logged as Failed."))
    if not frappe.db.exists("Email Account", {"default_outgoing": 1, "enabled": 1}):
        problems.append(
            _("No enabled default outgoing Email Account on this site, so no mail can be sent.")
        )
    if not frappe.db.exists("Notifire Group", {"fallback": 1, "enabled": 1}):
        problems.append(
            _("No fallback group: events with no site (bench and deploy) will not be delivered.")
        )
    if counts["failed_24h"]:
        problems.append(
            _("{0} notification(s) failed in the last 24 hours.").format(counts["failed_24h"])
        )

    counts["problems"] = problems
    return counts


@frappe.whitelist(methods=["POST"])
def global_secret(rotate=0):
    """Read (or rotate) the global fallback secret."""
    frappe.has_permission("Notifire Settings", "write", throw=True)
    if frappe.utils.cint(rotate):
        settings = frappe.get_doc("Notifire Settings")
        settings.fallback_secret = secrets.token_hex(24)
        settings.save()
    return {"secret": utils.global_webhook_secret()}


@frappe.whitelist(methods=["POST"])
def send_test_email(recipient):
    """Send a sample notification through the real delivery path."""
    frappe.has_permission("Notifire Settings", "write", throw=True)

    recipient = (recipient or "").strip()
    if not frappe.utils.validate_email_address(recipient):
        frappe.throw(_("Invalid email address: {0}").format(recipient))

    payload = {
        "event": "Notifire Test",
        "data": {
            "site": "example.frappe.cloud",
            "status": "Active",
            "note": "This is a test notification from Notifire Settings.",
        },
    }
    subject, text_body, html_body = utils.build_notification(
        "Notifire Test", "example.frappe.cloud", payload
    )
    ok, error = utils.deliver_message(subject, text_body, html_body, [recipient])
    return {"ok": ok, "error": error}


@frappe.whitelist(methods=["POST"])
def resend_log(log):
    """Retry delivery for a Failed or Suppressed log entry, ignoring dedupe."""
    doc = frappe.get_doc("Notifire Log", log)
    doc.check_permission("write")
    return utils.resend_log(doc.name)
