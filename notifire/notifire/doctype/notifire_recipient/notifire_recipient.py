# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address

ALL_SITES = "All sites in this group"
SELECTED_SITES = "Only selected sites"


class NotifireRecipient(Document):
    def validate(self):
        self.email = (self.email or "").strip()
        if not validate_email_address(self.email):
            frappe.throw(_("Invalid email address: {0}").format(self.email))
        self.apply_scope_mode()
        self.validate_scope_group()
        self.validate_duplicate()

    def apply_scope_mode(self):
        """Keep `scope_mode` and the `applies_to` rows consistent.

        `applies_to` stays the single source of truth for routing (empty =
        group default). `scope_mode` exists so the rule is visible in the
        form instead of hiding behind an empty table.
        """
        rows, seen = [], set()
        for row in self.get("applies_to") or []:
            hostname = (row.hostname or "").strip().lower()
            if hostname and hostname not in seen:
                seen.add(hostname)
                row.hostname = hostname
                rows.append(row)

        if not self.scope_mode:
            self.scope_mode = SELECTED_SITES if rows else ALL_SITES

        if self.scope_mode == ALL_SITES:
            rows = []
        elif not rows:
            frappe.throw(
                _("Select at least one site, or set <b>Receives events for</b> to <b>{0}</b>.").format(
                    ALL_SITES
                )
            )
        self.set("applies_to", rows)

    def validate_scope_group(self):
        """A selected site must belong to this recipient's group.

        Selecting a hostname from another group would look like it works and
        then never fire, because routing resolves the group first.
        """
        for row in self.get("applies_to") or []:
            owner = frappe.db.get_value("Notifire Site", row.hostname, "group")
            if not owner:
                frappe.throw(
                    _("{0} is not a mapped hostname. Add it to a group first.").format(
                        frappe.bold(row.hostname)
                    )
                )
            if owner != self.group:
                frappe.throw(
                    _(
                        "{0} routes to group {1}, not {2}. Events for it would never reach this address."
                    ).format(frappe.bold(row.hostname), frappe.bold(owner), frappe.bold(self.group))
                )

    def validate_duplicate(self):
        # One row per address per group (case-insensitive): the address's
        # "scope" is the set of sites it covers, so duplicates only confuse.
        filters = {"group": self.group}
        if self.name:
            filters["name"] = ("!=", self.name)
        rows = frappe.get_all("Notifire Recipient", filters=filters, fields=["name", "email"])
        target = self.email.lower()
        for row in rows:
            if (row.email or "").strip().lower() == target:
                frappe.throw(
                    _(
                        "{0} is already a recipient of this group. Open that row and change its sites instead."
                    ).format(frappe.bold(self.email))
                )
