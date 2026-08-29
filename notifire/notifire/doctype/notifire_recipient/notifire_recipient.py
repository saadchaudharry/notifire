# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address


class NotifireRecipient(Document):
    def validate(self):
        self.email = (self.email or "").strip()
        if not validate_email_address(self.email):
            frappe.throw(_("Invalid email address: {0}").format(self.email))
        self.normalize_scopes()
        self.validate_duplicate()

    def normalize_scopes(self):
        rows = []
        for row in self.get("applies_to") or []:
            hostname = (row.hostname or "").strip().lower()
            if hostname:
                row.hostname = hostname
                rows.append(row)
        self.set("applies_to", rows)

    def validate_duplicate(self):
        # One row per address per group (case-insensitive). The address
        # "scope" is the set of hostnames it applies to, so duplicates would
        # only be confusing.
        filters = {"group": self.group}
        if self.name:
            filters["name"] = ("!=", self.name)
        rows = frappe.get_all("Notifire Recipient", filters=filters, fields=["name", "email"])
        target = self.email.lower()
        if any((row.email or "").strip().lower() == target for row in rows):
            frappe.throw(
                _(
                    "This recipient already exists in this group. Edit its 'Applies to' hostnames to change which sites it covers."
                )
            )
