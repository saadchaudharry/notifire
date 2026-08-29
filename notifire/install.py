# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import secrets

import frappe
from frappe.utils.password import get_decrypted_password


def after_install():
    """Seed Notifire Settings with safe defaults and a global fallback secret.

    The fallback secret plays the role of the old WEBHOOK_SECRET env var:
    a master key accepted by every webhook endpoint. Per-group secrets keep
    working independently (and are preferred).
    """
    settings = frappe.get_doc("Notifire Settings")
    if not get_decrypted_password(
        "Notifire Settings", "Notifire Settings", "fallback_secret", raise_exception=False
    ):
        settings.fallback_secret = secrets.token_hex(24)
    if settings.get("dedupe_window_minutes") in (None, ""):
        settings.dedupe_window_minutes = 10
    if not settings.get("email_subject_prefix"):
        settings.email_subject_prefix = "Notifire"
    settings.flags.ignore_permissions = True
    settings.save()
