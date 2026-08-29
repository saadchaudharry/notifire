# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import re
import secrets

import frappe
from frappe import _
from frappe.model.document import Document

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def slugify(value):
    value = re.sub(r"[^a-z0-9]+", "-", str(value).strip().lower()).strip("-")
    return value or "group"


class NotifireGroup(Document):
    def validate(self):
        self.normalize_slug()
        self.normalize_hostnames()
        self.validate_hostname_uniqueness()

    def before_insert(self):
        # Auto-generate a ready-to-copy webhook secret (48-char hex) unless
        # one was provided programmatically. Existing secrets are never
        # touched on update - use "Rotate Secret" to replace one.
        if not self.get("secret"):
            self.secret = secrets.token_hex(24)

    def on_update(self):
        # Enforce a single fallback group.
        if self.fallback:
            frappe.db.sql(
                "update `tabNotifire Group` set fallback=0 where name != %(name)s and fallback=1",
                {"name": self.name},
            )

    def normalize_slug(self):
        if not self.slug and self.title:
            self.slug = slugify(self.title)
        self.slug = (self.slug or "").strip().lower()
        if not SLUG_RE.match(self.slug or ""):
            frappe.throw(_("Slug may only contain lowercase letters, numbers and hyphens."))

    def normalize_hostnames(self):
        rows = []
        for row in self.get("hostnames") or []:
            hostname = (row.hostname or "").strip().lower()
            if hostname:
                row.hostname = hostname
                rows.append(row)
        self.set("hostnames", rows)

    def validate_hostname_uniqueness(self):
        seen = set()
        for row in self.get("hostnames") or []:
            hostname = row.hostname
            if hostname in seen:
                frappe.throw(_("Hostname {0} is listed twice in this group.").format(hostname))
            seen.add(hostname)

            filters = {"hostname": hostname, "parenttype": "Notifire Group"}
            if self.name:
                filters["parent"] = ("!=", self.name)
            clash = frappe.get_all(
                "Notifire Group Hostname",
                filters=filters,
                fields=["parent"],
                limit_page_length=1,
            )
            if clash:
                frappe.throw(
                    _("Hostname {0} is already covered by group {1} - a site can only route to one group.").format(
                        hostname, clash[0].parent
                    )
                )
