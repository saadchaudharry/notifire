# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from notifire.notifire import utils
from notifire.notifire.doctype.notifire_group.notifire_group_test import make_group, make_recipient


class TestNotifireRecipient(FrappeTestCase):
    def test_invalid_email_rejected(self):
        group = make_group("Emails")
        with self.assertRaises(frappe.ValidationError):
            make_recipient(group, "not-an-email")

    def test_duplicate_case_insensitive_rejected(self):
        group = make_group("Emails Two")
        make_recipient(group, "ops@example.com")
        with self.assertRaises(frappe.ValidationError):
            make_recipient(group, "OPS@EXAMPLE.COM")

    def test_same_email_in_different_groups_ok(self):
        g1 = make_group("GA")
        g2 = make_group("GB")
        make_recipient(g1, "ops@example.com")
        make_recipient(g2, "ops@example.com")

    def test_scope_lowercased(self):
        group = make_group("Scope", ["h1.example.com"])
        recipient = make_recipient(group, "x@example.com", applies_to=["H1.Example.COM"])
        self.assertEqual(recipient.get("applies_to")[0].hostname, "h1.example.com")

    def test_disabled_recipient_excluded(self):
        group = make_group("Disabled", ["h1.example.com"])
        recipient = make_recipient(group, "x@example.com")
        recipient.enabled = 0
        recipient.save()
        recipients, _, _ = utils.resolve_recipients("h1.example.com")
        self.assertEqual(recipients, [])
