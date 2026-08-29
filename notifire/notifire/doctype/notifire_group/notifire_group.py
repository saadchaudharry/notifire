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

    def on_trash(self):
        """Delete cleanly instead of failing with a raw link error.

        Hostnames are deliberately *not* deleted for you: they usually need
        to move to another group, and deleting them silently would stop
        notifications for real production sites.
        """
        sites = frappe.get_all("Notifire Site", filters={"group": self.name}, pluck="name")
        if sites:
            shown = ", ".join(sites[:5]) + ("\u2026" if len(sites) > 5 else "")
            frappe.throw(
                _("{0} hostname(s) still route to this group ({1}). Move or delete them first.").format(
                    len(sites), shown
                )
            )

        for name in frappe.get_all("Notifire Recipient", filters={"group": self.name}, pluck="name"):
            frappe.delete_doc("Notifire Recipient", name, ignore_permissions=True, delete_permanently=True)

        # Logs are history: keep them, just drop the dangling link.
        frappe.db.set_value("Notifire Log", {"group": self.name}, "group", "", update_modified=False)

    def normalize_slug(self):
        if not self.slug and self.title:
            self.slug = slugify(self.title)
        self.slug = (self.slug or "").strip().lower()
        if not SLUG_RE.match(self.slug or ""):
            frappe.throw(_("Slug may only contain lowercase letters, numbers and hyphens."))
