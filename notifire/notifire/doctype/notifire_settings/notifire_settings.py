# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import cint


class NotifireSettings(Document):
    def validate(self):
        # 0 disables the guard; a day is plenty as an upper bound.
        self.dedupe_window_minutes = max(0, min(cint(self.dedupe_window_minutes), 1440))
