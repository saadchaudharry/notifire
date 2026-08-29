# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

from frappe.model.document import Document

DEFAULT_DEDUPE_MINUTES = 10
MAX_DEDUPE_MINUTES = 1440


class NotifireSettings(Document):
    def validate(self):
        # Clamp the dedupe window to a sane range (0 disables; max 1 day).
        try:
            minutes = int(self.dedupe_window_minutes)
        except (TypeError, ValueError):
            minutes = DEFAULT_DEDUPE_MINUTES
        self.dedupe_window_minutes = max(0, min(minutes, MAX_DEDUPE_MINUTES))
