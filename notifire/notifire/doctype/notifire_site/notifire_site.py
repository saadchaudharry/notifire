# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""A single Frappe Cloud site hostname mapped to one notification group.

Hostnames used to live in a child table on Notifire Group. They are their
own DocType now so that:

  * the docname *is* the hostname, which makes cross-group uniqueness a
    database guarantee instead of a hand-written validation;
  * recipients can pick hostnames from a real link field (autocomplete,
    no silent typos);
  * you can search, filter and bulk-edit the whole hostname map from one
    list view.
"""

import frappe
from frappe import _
from frappe.model.document import Document

from notifire.notifire import utils


def normalize_hostname(value):
    return (value or "").strip().lower().rstrip(".")


class NotifireSite(Document):
    def autoname(self):
        # Runs before validate, so normalize here too: the docname and the
        # hostname field must always agree.
        self.hostname = normalize_hostname(self.hostname)
        self.name = self.hostname

    def validate(self):
        self.hostname = normalize_hostname(self.hostname)
        self.label = (self.label or "").strip()
        if not self.hostname:
            frappe.throw(_("Hostname is required."))
        if not utils.looks_like_hostname(self.hostname):
            frappe.throw(
                _(
                    "{0} does not look like a site hostname. Expected something like <b>test465.frappe.cloud</b>."
                ).format(frappe.bold(self.hostname))
            )

    def on_update(self):
        utils.update_site_count(self.group)
        if self.has_value_changed("group"):
            # Recipient scopes belong to one group; a moved hostname must not
            # keep granting mail to the old group's recipients.
            removed = utils.clear_foreign_scopes(self.hostname, self.group)
            if removed:
                frappe.msgprint(
                    _("Removed {0} recipient scope(s) that belonged to the previous group.").format(removed),
                    indicator="orange",
                    alert=True,
                )
            previous = self.get_doc_before_save()
            if previous and previous.group:
                utils.update_site_count(previous.group)

    def on_trash(self):
        # Link fields would block the delete otherwise; scoped recipients
        # simply lose this hostname from their "Applies to" list.
        utils.clear_scopes_for_hostname(self.hostname)

    def after_delete(self):
        utils.update_site_count(self.group)
