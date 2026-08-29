# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

from frappe.model.document import Document


class NotifireGroupHostname(Document):
    def validate(self):
        # Hostnames are case-insensitive; store lowercase so routing and
        # dedupe match exactly on every database backend.
        self.hostname = (self.hostname or "").strip().lower()
