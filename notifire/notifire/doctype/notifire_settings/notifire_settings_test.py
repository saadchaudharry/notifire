# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from notifire.notifire import utils


class TestNotifireSettings(FrappeTestCase):
    def test_dedupe_window_defaults_and_clamps(self):
        settings = frappe.get_doc("Notifire Settings")
        settings.dedupe_window_minutes = None
        settings.save()
        self.assertEqual(utils.dedupe_window_minutes(), 10)

        settings.dedupe_window_minutes = 99999
        settings.save()
        self.assertEqual(utils.dedupe_window_minutes(), 1440)

        settings.dedupe_window_minutes = 25
        settings.save()
        self.assertEqual(utils.dedupe_window_minutes(), 25)

    def test_subject_prefix_default_and_override(self):
        self.assertEqual(utils.subject_prefix(), "Notifire")
        settings = frappe.get_doc("Notifire Settings")
        settings.email_subject_prefix = "Ops"
        settings.save()
        self.assertEqual(utils.subject_prefix(), "Ops")

    def test_notifications_enabled_default(self):
        self.assertTrue(utils.notifications_enabled())

    def test_global_secret_roundtrip(self):
        settings = frappe.get_doc("Notifire Settings")
        settings.fallback_secret = "abc123-global"
        settings.save()
        self.assertEqual(utils.global_webhook_secret(), "abc123-global")

    def test_is_valid_secret_fail_closed(self):
        self.assertFalse(utils.is_valid_secret(""))
        self.assertFalse(utils.is_valid_secret("x", group_secret="", global_secret=""))
        self.assertTrue(utils.is_valid_secret("a", group_secret="a", global_secret=""))
        self.assertTrue(utils.is_valid_secret("b", group_secret="", global_secret="b"))
        self.assertFalse(utils.is_valid_secret("a", group_secret="b", global_secret="c"))
