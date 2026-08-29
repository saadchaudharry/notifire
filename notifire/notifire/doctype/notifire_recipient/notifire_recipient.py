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

        known = set(frappe.get_all("Bench Group Hostname", pluck="hostname"))
        rows, seen = [], set()
        for row in self.hostnames or []:
            host = (row.hostname or "").strip().lower()
            if not host or host in seen:
                continue
            if host not in known:
                frappe.throw(
                    _("{0} is not listed on any Bench Group. Add it there first.").format(
                        frappe.bold(host)
                    )
                )
            row.hostname = host
            seen.add(host)
            rows.append(row)
        self.set("hostnames", rows)
