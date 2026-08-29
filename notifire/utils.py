# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Everything that happens after a webhook is authenticated.

    extract site -> find recipients -> log -> send email -> update log
"""

import hmac
import json
import re
from datetime import datetime, timedelta

import frappe

# a.b.c style hostnames only. Rejects bench/deploy ids such as
# "bench-0019-000059-f2-london", "deploy-0019-000059", "368704046d".
HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", re.IGNORECASE
)

GREEN = {
    "active", "live", "up", "running", "online", "healthy", "ok", "success",
    "succeeded", "complete", "completed", "ready", "deployed", "published",
    "passed", "available",
}
RED = {
    "broken", "down", "failed", "failure", "error", "crashed", "dead",
    "offline", "suspended", "deleted", "cancelled", "canceled", "unreachable",
}

# Everything else (installing, pending, preparing, updating, archived, ...)
# is yellow: in progress or needs a look.
BALL_GREEN = "\U0001F7E2"
BALL_YELLOW = "\U0001F7E1"
BALL_RED = "\U0001F534"

# Frappe Cloud bookkeeping keys we never put in an email.
NOISE = {
    "doctype", "owner", "creation", "modified", "modified_by", "docstatus",
    "idx", "team", "tags", "ip", "signup_time", "account_request",
    "skip_auto_updates", "additional_system_user_created", "retry_count",
    "is_database_access_enabled", "archive_failed", "setup_wizard_complete",
    "database_access_connection_limit", "is_ssh_proxy_setup",
    "inplace_update_docker_image",
}

EMAIL_HTML = """<!DOCTYPE html>
<html>
<body style="margin:0;padding:0">
  <table width="100%" cellspacing="0" cellpadding="0">
    <tr><td align="center">
      <table width="600" cellspacing="0" cellpadding="0" style="max-width:600px">
        <tr><td style="padding:20px 0;text-align:center">
          <img src="https://frappe.io/files/framework.png" alt="Notifire" width="70">
        </td></tr>
        <tr><td style="padding:0 20px 20px">
          <h2>{% if ball %}{{ ball }} {% endif %}{{ event }}</h2>
          {% for label, value in rows %}
          <p style="margin:4px 0"><strong>{{ label }}:</strong> {{ value }}</p>
          {% endfor %}
        </td></tr>
        <tr><td style="background:#f5f5f5;padding:20px;text-align:center">
          &copy; Your Deployment buddy Notifire Bot.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def settings():
    return frappe.get_cached_doc("Notifire Settings")


def status_ball(status):
    """Traffic-light emoji for a Frappe Cloud status. Empty when no status."""
    value = str(status or "").strip().lower()
    if not value:
        return ""
    if value in GREEN:
        return BALL_GREEN
    if value in RED:
        return BALL_RED
    return BALL_YELLOW


def valid_secret(provided, *expected):
    """Constant-time check against any of the accepted secrets."""
    if not provided:
        return False
    given = str(provided).encode()
    return any(e and hmac.compare_digest(given, str(e).encode()) for e in expected)


def extract_site(payload):
    """The site hostname in a payload, or None for bench/deploy events.

    Site Plan Change carries data.site, Site Status Update carries
    data.host_name (and data.name). Bench and deploy events carry ids like
    "bench-0019-000059-f2-london", which must never be read as a hostname.
    """
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    for key in ("site", "host_name", "name"):
        value = data.get(key)
        if isinstance(value, str) and HOSTNAME_RE.match(value.strip()):
            return value.strip().lower()
    return None


def find_recipients(site):
    """Enabled recipients for a hostname.

    A recipient with no hostnames listed gets everything - that is also who
    receives bench and deploy events, which have no site at all.
    """
    emails, seen = [], set()
    for row in frappe.get_all(
        "Notifire Recipient", filters={"enabled": 1}, fields=["name", "email"], order_by="creation asc"
    ):
        hosts = [
            h.strip().lower()
            for h in frappe.get_all(
                "Notifire Recipient Hostname", filters={"parent": row.name}, pluck="hostname"
            )
            if h
        ]
        if hosts and not (site and site in hosts):
            continue
        key = (row.email or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            emails.append(row.email.strip())
    return emails


def build_rows(event, site, data):
    """The (label, value) lines shown in the email."""
    rows = [("Event", event)]
    if site:
        rows.append(("Site", site))
    if data.get("status"):
        rows.append(("Status", str(data["status"])))
    if data.get("from_plan") or data.get("to_plan"):
        rows.append(("Change", "{} \u2192 {}".format(data.get("from_plan", "?"), data.get("to_plan", "?"))))
    if data.get("name") and not site:
        rows.append(("Reference", str(data["name"])))

    shown = {label.lower() for label, _ in rows} | {"from_plan", "to_plan", "name", "host_name"}
    for key, value in data.items():
        if key.lower() in shown or key.lower() in NOISE or isinstance(value, (dict, list)):
            continue
        rows.append((key.replace("_", " ").title(), str(value)))
    return rows


def send_email(event, site, payload, recipients, log_name=None):
    """Send one notification. Returns (ok, error)."""
    conf = settings()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    ref = site or data.get("name") or ""
    ball = status_ball(data.get("status"))

    subject = "[{}] {}".format(conf.email_subject_prefix or "Notifire", event)
    if ref:
        subject += " - {}".format(ref)
    if ball:
        subject = "{} {}".format(ball, subject)

    rows = build_rows(event, site, data)
    try:
        frappe.sendmail(
            recipients=recipients,
            sender=conf.from_email or "",
            subject=subject,
            message=frappe.render_template(EMAIL_HTML, {"event": event, "ball": ball, "rows": rows}),
            text_content="\n".join("{}: {}".format(l, v) for l, v in rows),
            reference_doctype="Notifire Log",
            reference_name=log_name,
            now=True,
        )
        return True, ""
    except Exception as exc:  # a mail failure must never break the webhook
        return False, "{}: {}".format(type(exc).__name__, exc)[:300]


def create_log(event, site, payload, group, recipients, status, error=""):
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return frappe.get_doc({
        "doctype": "Notifire Log",
        "event": event,
        "site": site or "",
        "reference": site or data.get("name") or "",
        "group": group or "",
        "recipients": ", ".join(recipients or []),
        "status": status,
        "error": error,
        "payload": frappe.as_json(payload)[:100000],
    }).insert(ignore_permissions=True)


def is_duplicate(event, site, reference, minutes):
    """True when the same event for the same site was emailed just now.

    A flapping site cycling Active -> Broken -> Active sends one webhook per
    transition, which is how you burn a daily mail quota in an hour.
    """
    if not minutes:
        return False
    filters = {
        "event": event,
        "status": "Sent",
        "creation": (">", datetime.utcnow() - timedelta(minutes=minutes)),
        "site": site or "",
    }
    if not site:
        filters["reference"] = reference or ""
    return bool(frappe.get_all("Notifire Log", filters=filters, limit_page_length=1))


def process_event(event, payload, group=None):
    """Handle one webhook event end to end. Returns the log status."""
    conf = settings()
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    site = extract_site(payload)
    reference = site or data.get("name") or ""
    recipients = find_recipients(site)

    log = create_log(event, site, payload, group, recipients, "Received")

    def finish(status, note=""):
        frappe.db.set_value("Notifire Log", log.name, {"status": status, "error": note})
        return status

    if not conf.enabled:
        return finish("Received", "Email notifications are turned off")

    if not recipients:
        return finish("Failed", "No recipient matches this event")

    if is_duplicate(event, site, reference, frappe.utils.cint(conf.dedupe_window_minutes)):
        return finish(
            "Suppressed",
            "Same event already emailed within the last {} minutes".format(conf.dedupe_window_minutes),
        )

    ok, error = send_email(event, site, payload, recipients, log.name)
    return finish("Sent" if ok else "Failed", error)


def parse_payload(raw):
    """Parse a webhook body. Returns (payload, error)."""
    try:
        payload = json.loads(raw) if raw else None
    except (ValueError, TypeError):
        return None, "Invalid JSON"
    if not isinstance(payload, dict):
        return None, "Payload must be a JSON object"
    event = payload.get("event")
    if not isinstance(event, str) or not event.strip():
        return None, "Missing event"
    return payload, None
