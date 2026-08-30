# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import hashlib
import re
import secrets

import frappe
from frappe import _
from frappe.model.document import Document

NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def fingerprint(token):
    """SHA-256 of a token, used as the group lookup key."""
    return hashlib.sha256(str(token or "").encode()).hexdigest()


class BenchGroup(Document):
    def before_insert(self):
        if not self.token:
            self.token = secrets.token_hex(24)

    def validate(self):
        if not NAME_RE.match(self.name or ""):
            frappe.throw(_("Use only letters, numbers, dots, dashes and underscores in the name."))

        # No query parameters: Frappe Cloud rejects an endpoint URL containing
        # "?". Every group posts to the same path and is identified by its
        # token instead.
        self.webhook_url = "{}/api/method/notifire.api.webhook".format(
            frappe.utils.get_url().rstrip("/")
        )

        self.set_token_hash()

        seen = set()
        for row in self.hostnames or []:
            row.hostname = (row.hostname or "").strip().lower()
            if row.hostname in seen:
                frappe.throw(_("Hostname {0} is listed twice.").format(row.hostname))
            seen.add(row.hostname)

        self.validate_hostnames_are_unique(seen)

    def set_token_hash(self):
        """Keep the fingerprint in step with the token.

        A Password field reads back as asterisks, so recompute only when the
        value in hand is a real token - otherwise a plain re-save would hash
        the mask and lock the group out of its own endpoint.
        """
        token = self.token or ""
        if not token or set(token) == {"*"}:
            return
        self.token_hash = fingerprint(token)

    def validate_hostnames_are_unique(self, hostnames):
        """One hostname, one group.

        Strict Site Binding is only as strong as this: without it, anyone who
        can edit a group could list another group's hostname on their own and
        pass the binding check with their own token.
        """
        if not hostnames:
            return

        taken = frappe.get_all(
            "Bench Group Hostname",
            filters={
                "hostname": ("in", list(hostnames)),
                "parenttype": "Bench Group",
                "parent": ("!=", self.name),
            },
            fields=["hostname", "parent"],
        )
        if taken:
            frappe.throw(
                _("{0} is already listed on bench group {1}.").format(
                    frappe.bold(taken[0].hostname), frappe.bold(taken[0].parent)
                )
            )
