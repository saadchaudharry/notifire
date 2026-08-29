# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

from frappe.model.document import Document


class NotifireRecipientScope(Document):
    def validate(self):
        # Scope hostnames are matched case-insensitively; store lowercase.
        self.hostname = (self.hostname or "").strip().lower()
