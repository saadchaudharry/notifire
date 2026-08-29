# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from notifire.notifire import utils


def make_group(title, hostnames=None, fallback=0, slug=None):
    return frappe.get_doc({
        "doctype": "Notifire Group",
        "title": title,
        "slug": slug,
        "fallback": fallback,
        "hostnames": [{"hostname": h} for h in (hostnames or [])],
    }).insert()


def make_recipient(group, email, applies_to=None, enabled=1):
    return frappe.get_doc({
        "doctype": "Notifire Recipient",
        "group": group.name,
        "email": email,
        "enabled": enabled,
        "applies_to": [{"hostname": h} for h in (applies_to or [])],
    }).insert()


class TestNotifireGroup(FrappeTestCase):
    def test_secret_auto_generated_and_slug_from_title(self):
        doc = make_group("Pre Prod Ops", ["Test465.Frappe.Cloud"])
        self.assertEqual(doc.slug, "pre-prod-ops")
        secret = doc.get_password("secret")
        self.assertEqual(len(secret), 48)
        # Hostnames are stored lowercase regardless of input case.
        self.assertEqual(doc.get("hostnames")[0].hostname, "test465.frappe.cloud")

    def test_invalid_slug_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            make_group("Bad Slug", slug="Not A Slug!")

    def test_only_one_fallback_group(self):
        make_group("Fallback Ops", fallback=1)
        second = make_group("Backup Fallback", fallback=1)
        names = frappe.get_all("Notifire Group", filters={"fallback": 1}, pluck="name")
        self.assertEqual(names, [second.name])

    def test_duplicate_hostname_in_group_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            make_group("Dup Host", ["a.example.com", "a.example.com"])

    def test_cross_group_hostname_rejected(self):
        make_group("G1", ["shared.example.com"])
        with self.assertRaises(frappe.ValidationError):
            make_group("G2", ["shared.example.com"])

    def test_extract_site_priority_and_lowercasing(self):
        self.assertEqual(utils.extract_site({"data": {"site": "A.B.com"}}), "a.b.com")
        self.assertEqual(
            utils.extract_site({"data": {"host_name": "H.Example.com"}}), "h.example.com"
        )
        self.assertEqual(
            utils.extract_site({"data": {"name": "site.example.com"}}), "site.example.com"
        )
        # bench/deploy/change ids are never mistaken for a site
        self.assertIsNone(utils.extract_site({"data": {"name": "bench-0019-000059-f2-london"}}))
        self.assertIsNone(utils.extract_site({"data": {"name": "368704046d"}}))
        self.assertIsNone(utils.extract_site({"data": {}}))
        self.assertIsNone(utils.extract_site({}))

    def test_resolve_recipients_scoped_replace_defaults(self):
        group = make_group("Routing", ["h1.example.com", "h2.example.com"])
        make_recipient(group, "scoped@example.com", applies_to=["h1.example.com"])
        make_recipient(group, "default@example.com")

        recipients, gname, used = utils.resolve_recipients("h1.example.com")
        self.assertEqual((recipients, gname, used), (["scoped@example.com"], group.name, False))

        # hostname matching is case-insensitive
        recipients, gname, used = utils.resolve_recipients("H2.Example.Com")
        self.assertEqual((recipients, gname, used), (["default@example.com"], group.name, False))

    def test_unknown_site_uses_fallback_group(self):
        fallback = make_group("FB", fallback=1)
        make_recipient(fallback, "ops@example.com")

        recipients, gname, used = utils.resolve_recipients("nowhere.example.com")
        self.assertEqual((recipients, gname, used), (["ops@example.com"], fallback.name, True))
        recipients, gname, used = utils.resolve_recipients(None)
        self.assertEqual(recipients, ["ops@example.com"])
