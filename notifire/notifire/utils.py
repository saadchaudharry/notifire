# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Notifire webhook processing layer (Frappe-native port).

Small, reusable helpers that implement the flow:

    Receive request -> Authenticate -> Parse JSON -> Validate event
        -> Extract site -> Resolve recipients -> Log -> Send notification
        -> Update log result

Kept intentionally simple: plain functions, no event bus, no extra
abstractions. Secrets never appear in logs, responses, or emails.
"""

import hmac
import json
import re
from datetime import datetime, timedelta

import frappe
from frappe import _
from frappe.utils.password import get_decrypted_password

DEFAULT_DEDUPE_MINUTES = 10
MAX_DEDUPE_MINUTES = 1440
MAX_PAYLOAD_CHARS = 100_000

# Keys we never render in notification emails (Frappe Cloud bookkeeping noise).
NOISY_DATA_KEYS = {
    "doctype", "owner", "creation", "modified", "modified_by", "docstatus",
    "idx", "team", "tags", "bench", "server", "ip", "label", "signup_time",
    "account_request", "skip_auto_updates", "additional_system_user_created",
    "is_database_access_enabled", "archive_failed", "setup_wizard_complete",
    "database_access_connection_limit", "trial_end_date",
}

# Human-friendly labels for common Frappe Cloud payload keys.
DATA_LABELS = {
    "site": "Site",
    "host_name": "Host",
    "name": "Name",
    "status": "Status",
    "plan": "Plan",
    "from_plan": "From Plan",
    "to_plan": "To Plan",
    "type": "Type",
    "cluster": "Cluster",
    "group": "Group",
    "build_start": "Build Start",
    "build_end": "Build End",
    "build_duration": "Build Duration",
    "timestamp": "Timestamp",
    "notify_email": "Notify Email",
}

# a.b.c style hostnames only. Deliberately rejects bench/deploy/change ids
# such as "bench-0019-000059-f2-london", "deploy-0019-000059", "368704046d".
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$",
    re.IGNORECASE,
)

# Traffic-light mapping for Frappe Cloud status strings. Drives the emoji
# status balls in notification emails (and the log form headline).
STATUS_GREEN = {
    "active", "live", "up", "running", "online", "healthy", "ok", "success",
    "succeeded", "complete", "completed", "ready", "deployed", "published",
    "passed", "available",
}
STATUS_RED = {
    "broken", "down", "failed", "failure", "error", "crashed", "dead",
    "offline", "suspended", "deleted", "cancelled", "canceled", "unreachable",
}
STATUS_YELLOW = {
    "installing", "installed", "updating", "updated", "rebooting",
    "restarting", "pending", "queued", "in progress", "processing",
    "maintenance", "backup", "backing up", "restoring", "syncing",
    "awaiting deployment", "building", "deploying", "trial", "unknown",
}

BALL_EMOJI = {"green": "\U0001F7E2", "yellow": "\U0001F7E1", "red": "\U0001F534"}

# Notification email body. Same copy and layout as the Django edition; plain
# table markup for maximum mail-client compatibility.
EMAIL_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Notifire Notification</title>
    <style>
        body, table, td, a { -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }
        table, td { mso-table-lspace: 0pt; mso-table-rspace: 0pt; }
        img { -ms-interpolation-mode: bicubic; }
        @media only screen and (max-width: 600px) { table[class="content"] { width: 100% !important; } }
    </style>
</head>
<body>
    <table width="100%" cellspacing="0" cellpadding="0">
        <tr>
            <td>
                <table class="content" align="center" width="600" cellspacing="0" cellpadding="0">
                    <tr>
                        <td style="padding: 20px 0; text-align: center;">
                            <img src="https://frappe.io/files/framework.png" alt="Notifire" width="70">
                        </td>
                    </tr>
                    <tr>
                        <td style="padding: 20px;">
                            <h2>{% if ball %}{{ ball }} {% endif %}{{ event }}</h2>
                            <p>Dear User,</p>
                            <p>Here is the latest webhook notification from Notifire.</p>
                            <div class="details">
                                {% for label, value in rows %}
                                <p><strong>{{ label }}:</strong> {{ value }}</p>
                                {% endfor %}
                            </div>
                            <p>If you have any questions or need further assistance, feel free to contact our support team.</p>
                        </td>
                    </tr>
                    <tr>
                        <td style="background: #f5f5f5; padding: 20px; text-align: center;">
                            &copy; Your Deployment buddy Notifire Bot.
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Settings (Notifire Settings single; secrets stay encrypted in the DB)
# ---------------------------------------------------------------------------

def notifications_enabled():
    value = frappe.db.get_single_value("Notifire Settings", "enabled")
    if value is None:
        return True
    return bool(int(value or 0))


def subject_prefix():
    return frappe.db.get_single_value("Notifire Settings", "email_subject_prefix") or "Notifire"


def dedupe_window_minutes():
    """Configured dedupe window in minutes. 0 disables. Clamped 0..1440."""
    raw = frappe.db.get_single_value("Notifire Settings", "dedupe_window_minutes")
    try:
        minutes = int(str(raw).strip())
    except (TypeError, ValueError):
        minutes = DEFAULT_DEDUPE_MINUTES
    return max(0, min(minutes, MAX_DEDUPE_MINUTES))


def global_webhook_secret():
    """The global fallback secret (Notifire Settings). Never exposed."""
    try:
        return get_decrypted_password(
            "Notifire Settings", "Notifire Settings", "fallback_secret", raise_exception=False
        ) or ""
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def is_valid_secret(provided, group_secret="", global_secret=""):
    """Constant-time comparison of the X-Webhook-Secret header value.

    Accepted, in order:
      1. The global fallback secret (master key for all endpoints), and/or
      2. The per-endpoint secret of the group being called.

    Fail closed: with neither configured, nothing authenticates.
    """
    if not provided:
        return False
    provided_bytes = str(provided).encode("utf-8")
    for expected in (global_secret, group_secret):
        if expected and hmac.compare_digest(provided_bytes, str(expected).encode("utf-8")):
            return True
    return False


# ---------------------------------------------------------------------------
# Payload parsing / site extraction
# ---------------------------------------------------------------------------

def parse_webhook_payload(raw_body):
    """Parse a webhook body safely.

    Returns (payload, error). error is None on success. A valid payload must
    be a JSON object; `data` may be missing or malformed and is treated as {}.
    """
    try:
        body = raw_body.decode("utf-8") if isinstance(raw_body, (bytes, bytearray)) else raw_body
        payload = json.loads(body) if body else None
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
        return None, "Invalid JSON"
    if not isinstance(payload, dict):
        return None, "Payload must be a JSON object"
    return payload, None


def payload_data(payload):
    """Return payload['data'] as a dict, tolerating missing/malformed values."""
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def looks_like_hostname(value):
    return isinstance(value, str) and bool(HOSTNAME_RE.match(value.strip()))


def extract_site(payload):
    """Identify the Frappe Cloud site from a webhook payload.

    Priority: data.site (Site Plan Change) -> data.host_name (Site Status
    Update) -> data.name (only when it actually looks like a hostname).

    Bench / deploy events carry no site hostname, so this returns None for
    them (they route to the fallback group). Never invents a fake site.

    The value is lowercased on purpose: hostnames are case-insensitive, and
    lowercasing keeps dedupe/recipient matching exact on every supported
    database (MariaDB, Postgres).
    """
    data = payload_data(payload)
    for key in ("site", "host_name", "name"):
        value = data.get(key)
        if looks_like_hostname(value):
            return value.strip().lower()
    return None


def status_ball(status):
    """Traffic-light emoji for a Frappe Cloud status string.

    Green = up / success, red = down / broken / failed, yellow = anything in
    progress or unrecognized (attention). Empty string when there is no
    status at all (so non-status events show no ball).
    """
    if not status:
        return ""
    value = str(status).strip().lower()
    if not value:
        return ""
    if value in STATUS_GREEN:
        return BALL_EMOJI["green"]
    if value in STATUS_RED:
        return BALL_EMOJI["red"]
    # Every other (transitional or unrecognized) status gets yellow.
    return BALL_EMOJI["yellow"]


def event_ref_name(event, site, data):
    """Display reference for logs/emails: site, else object name, else event."""
    ref = site or data.get("name") or ""
    return str(ref) if ref else ""


# ---------------------------------------------------------------------------
# Hostname registry (Notifire Site)
# ---------------------------------------------------------------------------

def update_site_count(group):
    """Keep Notifire Group.site_count in sync for the list view."""
    if not group or not frappe.db.exists("Notifire Group", group):
        return
    count = frappe.db.count("Notifire Site", {"group": group})
    frappe.db.set_value("Notifire Group", group, "site_count", count, update_modified=False)


def clear_scopes_for_hostname(hostname, group=None):
    """Delete recipient scope rows pointing at a hostname.

    `group` narrows the deletion to recipients that do *not* belong to that
    group, which is what a hostname move needs.
    """
    hostname = (hostname or "").strip().lower()
    if not hostname:
        return 0

    rows = frappe.get_all(
        "Notifire Recipient Scope",
        filters={"parenttype": "Notifire Recipient", "hostname": hostname},
        fields=["name", "parent"],
    )
    if not rows:
        return 0

    parents = {row.parent for row in rows}
    keep = set()
    if group:
        for parent in parents:
            if frappe.db.get_value("Notifire Recipient", parent, "group") == group:
                keep.add(parent)

    removed = 0
    touched = set()
    for row in rows:
        if row.parent in keep:
            continue
        frappe.db.delete("Notifire Recipient Scope", {"name": row.name})
        touched.add(row.parent)
        removed += 1

    # A scoped recipient that just lost its last hostname would otherwise
    # silently become a group default - flip it back explicitly.
    for parent in touched:
        remaining = frappe.db.count(
            "Notifire Recipient Scope", {"parenttype": "Notifire Recipient", "parent": parent}
        )
        if not remaining:
            frappe.db.set_value(
                "Notifire Recipient", parent, "scope_mode", "All sites in this group",
                update_modified=False,
            )
    return removed


def clear_foreign_scopes(hostname, group):
    """Drop scope rows for a hostname that belong to some *other* group."""
    return clear_scopes_for_hostname(hostname, group=group)


# ---------------------------------------------------------------------------
# Recipient resolution
# ---------------------------------------------------------------------------

def find_group_for_site(site):
    """The enabled group this hostname routes to, or None.

    Hostnames live in the Notifire Site registry, whose docname *is* the
    lowercase hostname, so the lookup is a primary-key hit and routing can
    never be ambiguous.
    """
    hostname = (site or "").strip().lower()
    if not hostname:
        return None
    row = frappe.db.get_value(
        "Notifire Site", hostname, ["group", "enabled"], as_dict=True
    )
    if not row or not row.enabled or not row.group:
        return None
    if not frappe.db.get_value("Notifire Group", row.group, "enabled"):
        return None
    return row.group


def get_fallback_group():
    rows = frappe.get_all(
        "Notifire Group",
        filters={"fallback": 1, "enabled": 1},
        order_by="creation asc",
        limit_page_length=1,
    )
    return rows[0].name if rows else None


def _recipient_rows(group_name):
    """Active recipients of a group, split into scoped and group-default."""
    scoped, defaults = [], []
    for row in frappe.get_all(
        "Notifire Recipient",
        filters={"group": group_name, "enabled": 1},
        fields=["name", "email"],
        order_by="creation asc",
    ):
        scopes = [
            (h or "").strip().lower()
            for h in frappe.get_all(
                "Notifire Recipient Scope",
                filters={"parent": row.name, "parenttype": "Notifire Recipient"},
                pluck="hostname",
            )
            if h and h.strip()
        ]
        if scopes:
            scoped.append((row.email, scopes))
        else:
            defaults.append(row.email)
    return scoped, defaults


def resolve_recipients(site):
    """Resolve who should receive a notification for a given site.

    Matching: the incoming hostname is looked up in the Notifire Site
    registry (case-insensitive). One group may cover many hostnames
    (multiple benches/sites on one Frappe Cloud account).

    Recipient precedence inside a matched group:
      1. Recipients scoped to the matched hostname (their "Selected sites"
         list contains it).
      2. Group-level default recipients (no site selection at all), used
         when the matched hostname has none of its own.
    Unknown/absent site -> fallback group recipients.

    Returns (recipients, group_name, used_fallback) where recipients is a
    clean, de-duplicated list of active email addresses.
    """
    group_name = None
    matched_hostname = None
    used_fallback = False
    if site:
        group_name = find_group_for_site(site)
        if group_name:
            matched_hostname = site.strip().lower()
    if not group_name:
        group_name = get_fallback_group()
        used_fallback = True

    recipients = []
    seen = set()

    def collect(addresses):
        for addr in addresses:
            clean = (addr or "").strip()
            key = clean.lower()
            if clean and key not in seen:
                seen.add(key)
                recipients.append(clean)

    if group_name:
        scoped, defaults = _recipient_rows(group_name)
        if matched_hostname:
            # Per-site recipients replace the group defaults for this site.
            collect(email for email, scopes in scoped if matched_hostname in scopes)
        if not recipients:
            collect(defaults)
    return recipients, group_name or "", used_fallback


# ---------------------------------------------------------------------------
# Dedupe window (anti email-storm)
# ---------------------------------------------------------------------------

def find_duplicate(event, site, ref_name, group_name, window_minutes):
    """Latest 'Sent' log with the same identity inside the window, or None.

    Identity = event + resolved group + site hostname. Payloads that carry
    no site (bench/deploy events) use the object ref_name instead, so two
    different benches never suppress each other.
    """
    cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
    filters = {
        "event": event,
        "group": group_name or "",
        "status": "Sent",
        "creation": (">", cutoff),
    }
    if site:
        filters["site"] = site
    else:
        filters["site"] = ""
        filters["ref_name"] = ref_name or ""
    rows = frappe.get_all(
        "Notifire Log",
        filters=filters,
        fields=["name", "creation"],
        order_by="creation desc",
        limit_page_length=1,
    )
    return rows[0] if rows else None


# ---------------------------------------------------------------------------
# Notification building & delivery
# ---------------------------------------------------------------------------

def build_subject(event, ref_name):
    subject = "[{}] {}".format(subject_prefix(), event)
    if ref_name:
        subject = "{} - {}".format(subject, ref_name)
    return subject


def build_detail_rows(event, site, data, received_at):
    """Ordered (label, value) rows describing the event for the email body."""
    rows = []
    rows.append(("Event", event))
    if site:
        rows.append(("Site", site))
    if data.get("status"):
        rows.append(("Status", str(data["status"])))
    if data.get("from_plan") or data.get("to_plan"):
        rows.append(("Change", "{} \u2192 {}".format(data.get("from_plan", "?"), data.get("to_plan", "?"))))
    if data.get("type"):
        rows.append(("Type", str(data["type"])))
    if data.get("cluster"):
        rows.append(("Cluster", str(data["cluster"])))
    if data.get("build_duration"):
        rows.append(("Build Duration", str(data["build_duration"])))

    # Timestamp: prefer the event's own timestamp, else when we received it.
    timestamp = data.get("timestamp") or received_at
    rows.append(("Timestamp", str(timestamp)))

    # Remaining meaningful payload keys, capped to keep emails readable.
    shown = {key.lower() for key, _ in rows} | {"from_plan", "to_plan"}
    extra = 0
    for key, value in data.items():
        if extra >= 10:
            rows.append(("\u2026", "additional payload fields omitted"))
            break
        if key.lower() in shown or key.lower() in NOISY_DATA_KEYS or key == "timestamp":
            continue
        if isinstance(value, (dict, list)):
            continue
        rows.append((DATA_LABELS.get(key, key.replace("_", " ").title()), str(value)))
        extra += 1
    return rows


def build_notification(event, site, payload, received_at=None):
    """Build (subject, text_body, html_body) for a webhook notification."""
    data = payload_data(payload)
    ref_name = event_ref_name(event, site, data)
    received_at = received_at or frappe.utils.now_datetime()
    rows = build_detail_rows(event, site, data, received_at)

    subject = build_subject(event, ref_name)
    text_body = "\n".join("{}: {}".format(label, value) for label, value in rows)
    html_body = frappe.render_template(
        EMAIL_HTML,
        {
            "event": event,
            "ball": status_ball(data.get("status")),
            "site": site or "",
            "ref_name": ref_name,
            "rows": rows,
            "timestamp": received_at,
        },
    )
    return subject, text_body, html_body


def deliver_message(subject, text_body, html_body, recipients, reference_name=None):
    """Send the notification email. Returns (ok, error_message).

    Sent synchronously (now=True) so the Notifire Log status reflects the
    real delivery attempt even on benches without background workers.
    Error messages are safe to store: they never contain credentials or
    secrets, only SMTP failure summaries.
    """
    from_email = frappe.db.get_single_value("Notifire Settings", "from_email") or ""
    try:
        frappe.sendmail(
            recipients=list(recipients),
            sender=from_email,
            subject=subject,
            message=html_body,
            text_content=text_body,
            reference_doctype="Notifire Log",
            reference_name=reference_name,
            now=True,
        )
        return True, ""
    except Exception as exc:  # SMTP failure must never crash the webhook
        return False, ("{}: {}".format(type(exc).__name__, str(exc)))[:300]


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def create_log(event, site, ref_name, payload, group, recipients,
               status, via_fallback=False, error=""):
    payload_str = frappe.as_json(payload if isinstance(payload, dict) else {})
    if len(payload_str) > MAX_PAYLOAD_CHARS:
        payload_str = payload_str[:MAX_PAYLOAD_CHARS]
    doc = frappe.get_doc({
        "doctype": "Notifire Log",
        "event": event,
        "site": site or "",
        "ref_name": ref_name or "",
        "payload": payload_str,
        "group": group or "",
        "sent_to": ", ".join(recipients or []),
        "status": status,
        "via_fallback": 1 if via_fallback else 0,
        "error": error or "",
    }).insert(ignore_permissions=True)
    return doc


# ---------------------------------------------------------------------------
# Main processing entry point
# ---------------------------------------------------------------------------

def process_webhook_event(event, payload):
    """Process a (non-validation) webhook event end to end.

    Returns a result dict:
        {"notification_status": "sent"|"failed"|"skipped"|"suppressed",
         "log": NotifireLog doc, "recipients": [...], "via_fallback": bool}
    """
    site = extract_site(payload)
    data = payload_data(payload)
    ref_name = event_ref_name(event, site, data)
    recipients, group, used_fallback = resolve_recipients(site)

    log = create_log(
        event=event,
        site=site,
        ref_name=ref_name,
        payload=payload,
        group=group,
        recipients=recipients,
        status="Received",
        via_fallback=used_fallback,
    )

    def finish(status, note, notification_status):
        frappe.db.set_value("Notifire Log", log.name, {"status": status, "error": note or None})
        log.status = status
        log.error = note
        return {
            "notification_status": notification_status,
            "log": log,
            "recipients": recipients,
            "via_fallback": used_fallback,
        }

    if not notifications_enabled():
        return finish(
            "Received",
            "Email notifications are disabled - webhook accepted, email skipped",
            "skipped",
        )

    if not recipients:
        suffix = " (site unknown, no fallback group)" if used_fallback else ""
        return finish(
            "Failed",
            "No recipients configured{} - notification not sent".format(suffix),
            "failed",
        )

    # --- Dedupe window: withhold repeat emails for the same event + site.
    # Checked after the recipients guard so undeliverable events keep
    # failing loudly instead of being silently swallowed here.
    window = dedupe_window_minutes()
    if window:
        duplicate = find_duplicate(event, site, ref_name, group, window)
        if duplicate is not None:
            return finish(
                "Suppressed",
                "Duplicate within the {} min dedupe window - email suppressed "
                "(same event last sent {}).".format(window, str(duplicate.creation or "")[:16]),
                "suppressed",
            )

    subject, text_body, html_body = build_notification(event, site, payload)
    ok, error = deliver_message(subject, text_body, html_body, recipients, log.name)

    if ok:
        return finish("Sent", "", "sent")
    return finish("Failed", error, "failed")


def resend_log(log_name):
    """Retry delivery for an existing log entry, ignoring the dedupe window.

    Recipients are resolved again rather than reused, so fixing the routing
    and pressing Send Now does what the operator expects.
    """
    log = frappe.get_doc("Notifire Log", log_name)
    try:
        payload = json.loads(log.payload) if isinstance(log.payload, str) else (log.payload or {})
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    event = log.event or payload.get("event") or "Notification"
    site = log.site or None
    recipients, group, used_fallback = resolve_recipients(site)

    if not recipients:
        note = _("Still no recipients for this event - nothing was sent.")
        frappe.db.set_value(
            "Notifire Log", log.name, {"status": "Failed", "error": note, "group": group or ""}
        )
        return {"ok": False, "message": note}

    subject, text_body, html_body = build_notification(event, site, payload)
    ok, error = deliver_message(subject, text_body, html_body, recipients, log.name)

    frappe.db.set_value(
        "Notifire Log",
        log.name,
        {
            "status": "Sent" if ok else "Failed",
            "error": "" if ok else error,
            "sent_to": ", ".join(recipients),
            "group": group or "",
            "via_fallback": 1 if used_fallback else 0,
        },
    )
    return {
        "ok": ok,
        "message": _("Sent to {0}").format(", ".join(recipients)) if ok else error,
    }
