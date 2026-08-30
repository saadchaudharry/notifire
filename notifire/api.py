# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""The webhook endpoint.

    POST /api/method/notifire.api.webhook
    Header: X-Webhook-Secret: <bench group token, or the global secret>

Frappe Cloud refuses an endpoint URL containing "?", so the group cannot be
named in a query parameter. The token identifies it instead: every group posts
to the same path, and the SHA-256 of the token is an indexed lookup key.

Guest-accessible because Frappe Cloud is not a Desk user, so every request is
authenticated by hand, then the payload's site must belong to the group whose
token was used.
"""

import secrets

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils.password import get_decrypted_password

from notifire import utils
from notifire.notifire.doctype.bench_group.bench_group import fingerprint

# Compared against when no group matched, so a wrong group name and a wrong
# token do the same work. Regenerated per process; never a valid token.
_DUMMY_TOKEN = secrets.token_hex(24)

MAX_BODY_BYTES = 512 * 1024


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=120, seconds=60)
def webhook():
    request = frappe.local.request
    provided = request.headers.get("X-Webhook-Secret", "") or ""

    # Authenticate before touching the body: an unauthenticated caller should
    # never get us to buffer whatever they feel like sending.
    group_name, hostnames = _authenticate(provided)

    # content_length is absent on chunked requests, so check it again after
    # reading. Neither stops a hostile client from making us buffer: the real
    # cap belongs in nginx (client_max_body_size).
    if (request.content_length or 0) > MAX_BODY_BYTES:
        frappe.throw(_("Payload too large"), frappe.ValidationError)

    raw = request.get_data() or b""
    if len(raw) > MAX_BODY_BYTES:
        frappe.throw(_("Payload too large"), frappe.ValidationError)

    payload, error = utils.parse_payload(raw.decode("utf-8", "replace"))
    if error:
        frappe.throw(_(error), frappe.ValidationError)

    event = payload["event"].strip()

    # Frappe Cloud sends this when you press Validate Webhook. Answer OK and
    # log it, but do not email anyone.
    if event == "Webhook Validate":
        utils.create_log(event, None, payload, group_name, [], "Received", "Webhook validated")
        return "OK"

    if utils.is_stale(payload):
        utils.create_log(event, None, payload, group_name, [], "Failed", "Event timestamp is too old")
        # Frappe rolls the transaction back on an unhandled exception, so a
        # rejected attempt leaves no trace unless it is committed first.
        frappe.db.commit()
        frappe.throw(_("Event too old"), frappe.ValidationError)

    # A token proves which group is calling, not which site it may speak for.
    # Without this check, any group's token can forge alerts for another
    # customer's site and reach the recipients scoped to it.
    site = utils.extract_site(payload)

    # The master key names no group, so take it from the site's own mapping.
    if not group_name and site:
        group_name = _group_for_site(site) or ""

    if site and hostnames is not None and site not in hostnames:
        utils.create_log(
            event, site, payload, group_name, [], "Failed", "Site is not listed on this bench group"
        )
        frappe.db.commit()  # keep the record of the attempt past the rollback
        frappe.throw(_("Unauthorized"), frappe.AuthenticationError)

    utils.process_event(event, payload, group=group_name)
    return "OK"


def _authenticate(provided):
    """Return (group name, allowed hostnames) or raise 401.

    The token is the identifier, so it is looked up by fingerprint: one
    indexed query whatever the secret is, valid or not. hostnames is None
    when no site binding applies (master key, or the switch is off).
    """
    name = None
    if provided:
        name = frappe.db.get_value(
            "Bench Group", {"token_hash": fingerprint(provided), "enabled": 1}, "name"
        )

    conf = utils.settings()

    if name:
        # Confirm against the stored secret too, so a fingerprint collision or
        # a tampered hash column is not enough on its own.
        token = get_decrypted_password("Bench Group", name, "token", raise_exception=False)
        if not utils.valid_secret(provided, token or _DUMMY_TOKEN):
            frappe.throw(_("Unauthorized"), frappe.AuthenticationError)

        if not frappe.utils.cint(conf.strict_site_binding):
            return name, None

        hostnames = {
            (h or "").strip().lower()
            for h in frappe.get_all(
                "Bench Group Hostname",
                filters={"parent": name, "parenttype": "Bench Group"},
                pluck="hostname",
            )
        }
        return name, hostnames

    # No group matched. The master key, if enabled, speaks for every group and
    # so carries no site binding.
    global_secret = ""
    if frappe.utils.cint(conf.allow_global_secret):
        global_secret = (
            get_decrypted_password(
                "Notifire Settings", "Notifire Settings", "webhook_secret", raise_exception=False
            )
            or ""
        )
    if not utils.valid_secret(provided, global_secret or _DUMMY_TOKEN):
        frappe.throw(_("Unauthorized"), frappe.AuthenticationError)
    return None, None


def _group_for_site(site):
    return frappe.db.get_value(
        "Bench Group Hostname", {"hostname": site, "parenttype": "Bench Group"}, "parent"
    )


# ---------------------------------------------------------------------------
# Desk helpers
# ---------------------------------------------------------------------------

def _group_for_write(group):
    """Load a group the user may write to, without leaking whether it exists.

    check_permission is per *document*, so User Permissions and share rules
    apply: a System Manager restricted to bench-0019 cannot read bench-0042's
    token. A doctype-level has_permission() would miss that.
    """
    if not frappe.db.exists("Bench Group", group):
        raise frappe.PermissionError
    doc = frappe.get_doc("Bench Group", group)
    doc.check_permission("write")
    return doc


@frappe.whitelist(methods=["POST"])
def get_token(group):
    """Reveal a group's token to someone who could regenerate it anyway."""
    return {"token": _group_for_write(group).get_password("token", raise_exception=False) or ""}


@frappe.whitelist(methods=["POST"])
def regenerate_token(group):
    """Replace a group's token. The old one stops working immediately."""
    doc = _group_for_write(group)
    doc.token = secrets.token_hex(24)
    doc.save()
    return {"token": doc.get_password("token")}


@frappe.whitelist(methods=["POST"])
def global_secret(rotate=0):
    """Read, or replace, the global secret."""
    frappe.has_permission("Notifire Settings", "write", throw=True)
    if frappe.utils.cint(rotate):
        conf = frappe.get_doc("Notifire Settings")
        conf.webhook_secret = secrets.token_hex(24)
        conf.save()
        frappe.clear_cache(doctype="Notifire Settings")
    return {
        "secret": get_decrypted_password(
            "Notifire Settings", "Notifire Settings", "webhook_secret", raise_exception=False
        )
        or ""
    }
