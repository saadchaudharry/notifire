# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import secrets

import frappe


def after_install():
    """Seed Notifire Settings with defaults and a global secret."""
    settings = frappe.get_doc("Notifire Settings")
    if not settings.webhook_secret:
        settings.webhook_secret = secrets.token_hex(24)
    if not settings.email_subject_prefix:
        settings.email_subject_prefix = "Notifire"
    if settings.dedupe_window_minutes in (None, ""):
        settings.dedupe_window_minutes = 10
    settings.enabled = 1
    # Secure defaults: site binding on, master key off.
    settings.strict_site_binding = 1
    settings.allow_global_secret = 0
    settings.flags.ignore_permissions = True
    settings.save()
