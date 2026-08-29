# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

from frappe.model.document import Document


class NotifireRecipientScope(Document):
    def validate(self):
        # The link target is a Notifire Site, whose docname is always the
        # lowercase hostname - normalize anyway for rows created via the API.
        self.hostname = (self.hostname or "").strip().lower()
