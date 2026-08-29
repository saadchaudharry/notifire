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

    def test_scope_mode_all_sites_clears_selection(self):
        group = make_group("ModeAll", ["h1.example.com"])
        recipient = make_recipient(group, "x@example.com", applies_to=["h1.example.com"])
        recipient.scope_mode = "All sites in this group"
        recipient.save()
        self.assertEqual(recipient.get("applies_to"), [])

    def test_scope_mode_selected_requires_a_site(self):
        group = make_group("ModeSelected", ["h1.example.com"])
        recipient = make_recipient(group, "x@example.com")
        recipient.scope_mode = "Only selected sites"
        with self.assertRaises(frappe.ValidationError):
            recipient.save()

    def test_scope_mode_inferred_when_missing(self):
        group = make_group("ModeInferred", ["h1.example.com"])
        recipient = frappe.get_doc({
            "doctype": "Notifire Recipient",
            "group": group.name,
            "email": "x@example.com",
            "applies_to": [{"hostname": "h1.example.com"}],
        }).insert()
        self.assertEqual(recipient.scope_mode, "Only selected sites")

    def test_scope_from_another_group_rejected(self):
        other = make_group("Foreign", ["foreign.example.com"])
        group = make_group("Local", ["local.example.com"])
        self.assertEqual(
            frappe.db.get_value("Notifire Site", "foreign.example.com", "group"), other.name
        )
        with self.assertRaises(frappe.ValidationError):
            make_recipient(group, "x@example.com", applies_to=["foreign.example.com"])

    def test_unknown_scope_rejected(self):
        group = make_group("UnknownScope", ["known.example.com"])
        with self.assertRaises(frappe.ValidationError):
            make_recipient(group, "x@example.com", applies_to=["ghost.example.com"])

    def test_duplicate_scope_rows_collapsed(self):
        group = make_group("DupScope", ["h1.example.com"])
        recipient = make_recipient(
            group, "x@example.com", applies_to=["h1.example.com", "h1.example.com"]
        )
        self.assertEqual(len(recipient.get("applies_to")), 1)

    def test_disabled_recipient_excluded(self):
        group = make_group("Disabled", ["h1.example.com"])
        recipient = make_recipient(group, "x@example.com")
        recipient.enabled = 0
        recipient.save()
        recipients, _, _ = utils.resolve_recipients("h1.example.com")
        self.assertEqual(recipients, [])
