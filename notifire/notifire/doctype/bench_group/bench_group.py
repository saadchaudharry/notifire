# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import re
import secrets

import frappe
from frappe import _
from frappe.model.document import Document

NAME_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


class BenchGroup(Document):
    def before_insert(self):
        if not self.token:
            self.token = secrets.token_hex(24)

    def validate(self):
        # The name goes straight into the webhook URL, so keep it URL-safe.
        # Naming it exactly like the Frappe Cloud bench group (bench-0019)
        # keeps the two dashboards readable side by side.
        if not NAME_RE.match(self.name or ""):
            frappe.throw(_("Use only letters, numbers, dots, dashes and underscores in the name."))

        self.webhook_url = "{}/api/method/notifire.api.webhook?group={}".format(
            frappe.utils.get_url().rstrip("/"), self.name
        )

        seen = set()
        for row in self.hostnames or []:
            row.hostname = (row.hostname or "").strip().lower()
            if row.hostname in seen:
                frappe.throw(_("Hostname {0} is listed twice.").format(row.hostname))
            seen.add(row.hostname)
