# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Everything that happens after a webhook is authenticated.

    extract site -> find recipients -> log -> send email -> update log
"""

import hmac
import json
import re

import frappe
from frappe.utils import escape_html

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

# Allowlist, not a denylist: a key Frappe Cloud adds tomorrow is not mailed
# out until someone puts it here on purpose. Order is display order.
EMAIL_FIELDS = [
    ("status", "Status"),
    ("deploy_candidate", "Deploy Candidate"),
    ("type", "Type"),
    ("plan", "Plan"),
    ("cluster", "Cluster"),
    ("group", "Bench Group"),
    ("server", "Server"),
    ("bench", "Bench"),
    ("build_start", "Build Start"),
    ("build_end", "Build End"),
    ("build_duration", "Build Duration"),
    ("build_error", "Build Error"),
    ("deployed", "Deployed"),
    ("trial_end_date", "Trial Ends"),
    ("timestamp", "Timestamp"),
]

# Reject a replayed capture whose own timestamp is ancient. Frappe Cloud only
# sends a static shared secret, so this is the only freshness signal there is.
STALE_EVENT_HOURS = 24

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
          <h2>{{ ball }} {{ event }}</h2>
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


def payload_data(payload):
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


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
    ok = False
    for candidate in expected:
        if candidate and hmac.compare_digest(given, str(candidate).encode()):
            ok = True  # no early return: keep the work constant
    return ok


def event_reference(site, data):
    """What the event is about, for logs, subjects and dedupe.

    Site events use the hostname. Bench and deploy events have none, and the
    live payload's `name` is an opaque hash ("6p4ajiomvd"), so prefer the
    readable ids Frappe Cloud sends alongside it.
    """
    if site:
        return site
    for key in ("deploy_candidate", "name", "group"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def extract_site(payload):
    """The site hostname in a payload, or None for bench/deploy events.

    Site Plan Change carries data.site, Site Status Update carries
    data.host_name (and data.name). Bench and deploy events carry ids like
    "bench-0019-000059-f2-london", which must never be read as a hostname.
    """
    data = payload_data(payload)
    for key in ("site", "host_name", "name"):
        value = data.get(key)
        if isinstance(value, str) and HOSTNAME_RE.match(value.strip()):
            return value.strip().lower()
    return None


def is_stale(payload):
    """True when the payload's own timestamp is older than the cutoff.

    Only a weak replay guard: events without a timestamp cannot be checked.
    """
    raw = payload_data(payload).get("timestamp")
    if not raw:
        return False
    try:
        sent = frappe.utils.get_datetime(raw)
    except Exception:
        return False
    if not sent:
        return False
    cutoff = frappe.utils.add_to_date(frappe.utils.now_datetime(), hours=-STALE_EVENT_HOURS)
    return sent < cutoff


def group_hostnames(group):
    if not group:
        return set()
    return {
        (h or "").strip().lower()
        for h in frappe.get_all(
            "Bench Group Hostname",
            filters={"parent": group, "parenttype": "Bench Group"},
            pluck="hostname",
        )
    }


def find_recipients(site, group=None):
    """Enabled recipients for an event, in two queries.

    With a site, a recipient matches if it lists that hostname. Bench and
    deploy events carry no site, so they fall back to the group that owns the
    token: anyone scoped to a hostname in that group gets its build and bench
    events too. Otherwise "list your sites" would silently mean "never hear
    about your own deploys".

    A recipient with no hostnames listed always matches.
    """
    scope = group_hostnames(group) if not site else None
    rows = frappe.get_all(
        "Notifire Recipient", filters={"enabled": 1}, fields=["name", "email"], order_by="creation asc"
    )
    if not rows:
        return []

    scoped = {}
    for row in frappe.get_all(
        "Notifire Recipient Hostname",
        filters={"parent": ("in", [r.name for r in rows]), "parenttype": "Notifire Recipient"},
        fields=["parent", "hostname"],
    ):
        scoped.setdefault(row.parent, set()).add((row.hostname or "").strip().lower())

    emails, seen = [], set()
    for row in rows:
        hosts = scoped.get(row.name)
        if hosts:
            if site:
                matches = site in hosts
            else:
                matches = bool(scope and hosts & scope)
            if not matches:
                continue
        key = (row.email or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            emails.append(row.email.strip())
    return emails


def build_rows(event, site, data):
    """Raw (label, value) lines for the email. The caller escapes them."""
    rows = [("Event", event)]
    if site:
        rows.append(("Site", site))
    if data.get("from_plan") or data.get("to_plan"):
        rows.append(("Change", "{} \u2192 {}".format(data.get("from_plan", "?"), data.get("to_plan", "?"))))
    if not site:
        reference = event_reference(site, data)
        if reference:
            rows.append(("Reference", reference))

    for key, label in EMAIL_FIELDS:
        value = data.get(key)
        if value in (None, "", "None") or isinstance(value, (dict, list)):
            continue
        rows.append((label, str(value)))

    return [(str(label), str(value)) for label, value in rows]


def send_email(event, site, payload, recipients, log_name=None):
    """Send one notification. Returns (ok, error)."""
    conf = settings()
    data = payload_data(payload)
    ref = event_reference(site, data)
    ball = status_ball(data.get("status"))

    # Subject is plain text, so it is not escaped - but it must not carry
    # newlines, which would let a payload inject mail headers.
    subject = "[{}] {}".format(conf.email_subject_prefix or "Notifire", event)
    if ref:
        subject += " - {}".format(ref)
    if ball:
        subject = "{} {}".format(ball, subject)
    subject = re.sub(r"[\r\n]+", " ", subject)[:200]

    # Frappe's Jinja environment does not autoescape and every value here came
    # from an external payload, so escape on the way into the template.
    rows = [(escape_html(l), escape_html(v)) for l, v in build_rows(event, site, data)]
    try:
        # No text_content: that is a parameter of the email queue, not of
        # frappe.sendmail. Frappe derives the plain-text alternative from the
        # HTML itself.
        frappe.sendmail(
            recipients=recipients,
            sender=conf.from_email or "",
            subject=subject,
            message=frappe.render_template(
                EMAIL_HTML, {"event": escape_html(event), "ball": ball, "rows": rows}
            ),
            reference_doctype="Notifire Log",
            reference_name=log_name,
            now=not frappe.utils.cint(conf.queue_emails),
        )
        return True, ""
    except Exception as exc:  # a mail failure must never break the webhook
        return False, "{}: {}".format(type(exc).__name__, exc)[:300]


def create_log(event, site, payload, group, recipients, status, error=""):
    data = payload_data(payload)
    return frappe.get_doc({
        "doctype": "Notifire Log",
        "event": event,
        "event_status": str(data.get("status") or ""),
        "site": site or "",
        "reference": event_reference(site, data),
        "group": group or "",
        "recipients": ", ".join(recipients or []),
        "status": status,
        "error": error,
        "payload": frappe.as_json(payload)[:100000],
    }).insert(ignore_permissions=True)


def is_duplicate(event, site, reference, event_status, minutes):
    """True when the same event for the same site was emailed just now.

    A flapping site cycling Active -> Broken -> Active sends one webhook per
    transition, which is how you burn a daily mail quota in an hour.

    The cutoff uses now_datetime(), i.e. the system timezone, because that is
    what Frappe writes into `creation`. Comparing against utcnow() silently
    stretches or disables the window by your UTC offset.
    """
    if not minutes:
        return False
    filters = {
        "event": event,
        # A build walking Pending -> Preparing -> Running is four different
        # events, not one repeated four times. Only an identical status is a
        # duplicate.
        "event_status": event_status or "",
        "status": "Sent",
        "creation": (">", frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-minutes)),
        "site": site or "",
    }
    if not site:
        filters["reference"] = reference or ""
    return bool(frappe.get_all("Notifire Log", filters=filters, limit_page_length=1))


def process_event(event, payload, group=None):
    """Handle one webhook event end to end. Returns the log status."""
    conf = settings()
    data = payload_data(payload)
    site = extract_site(payload)
    reference = event_reference(site, data)
    recipients = find_recipients(site, group)

    log = create_log(event, site, payload, group, recipients, "Received")

    def finish(status, note=""):
        frappe.db.set_value("Notifire Log", log.name, {"status": status, "error": note})
        return status

    if not conf.enabled:
        return finish("Received", "Email notifications are turned off")

    if not recipients:
        return finish("Failed", "No recipient matches this event")

    if is_duplicate(
        event, site, reference, data.get("status"), frappe.utils.cint(conf.dedupe_window_minutes)
    ):
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
