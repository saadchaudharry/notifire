# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from notifire.notifire import api, utils


def make_group(title, hostnames=None, fallback=0, slug=None):
    """Create a group and map hostnames to it.

    Hostnames are their own DocType now, so the helper keeps the old
    signature and creates the Notifire Site rows behind it.
    """
    group = frappe.get_doc({
        "doctype": "Notifire Group",
        "title": title,
        "slug": slug,
        "fallback": fallback,
    }).insert()

    for hostname in hostnames or []:
        frappe.get_doc({
            "doctype": "Notifire Site",
            "hostname": hostname,
            "group": group.name,
        }).insert()

    group.reload()
    return group


def make_recipient(group, email, applies_to=None, enabled=1):
    return frappe.get_doc({
        "doctype": "Notifire Recipient",
        "group": group.name,
        "email": email,
        "enabled": enabled,
        "scope_mode": "Only selected sites" if applies_to else "All sites in this group",
        "applies_to": [{"hostname": h} for h in (applies_to or [])],
    }).insert()


class TestNotifireGroup(FrappeTestCase):
    def test_secret_auto_generated_and_slug_from_title(self):
        doc = make_group("Pre Prod Ops", ["Test465.Frappe.Cloud"])
        self.assertEqual(doc.slug, "pre-prod-ops")
        secret = doc.get_password("secret")
        self.assertEqual(len(secret), 48)
        # Hostnames are stored lowercase regardless of input case, and the
        # docname is the hostname itself.
        self.assertTrue(frappe.db.exists("Notifire Site", "test465.frappe.cloud"))
        self.assertEqual(doc.site_count, 1)

    def test_invalid_slug_rejected(self):
        with self.assertRaises(frappe.ValidationError):
            make_group("Bad Slug", slug="Not A Slug!")

    def test_only_one_fallback_group(self):
        make_group("Fallback Ops", fallback=1)
        second = make_group("Backup Fallback", fallback=1)
        names = frappe.get_all("Notifire Group", filters={"fallback": 1}, pluck="name")
        self.assertEqual(names, [second.name])

    def test_cross_group_hostname_rejected(self):
        make_group("G1", ["shared.example.com"])
        with self.assertRaises(Exception):
            make_group("G2", ["shared.example.com"])

    def test_group_with_hostnames_cannot_be_deleted(self):
        group = make_group("Busy", ["keep.example.com"])
        with self.assertRaises(frappe.ValidationError):
            group.delete()

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

    def test_disabled_hostname_falls_through_to_fallback(self):
        fallback = make_group("FallbackForDisabled", fallback=1)
        make_recipient(fallback, "fb@example.com")
        group = make_group("HasDisabled", ["off.example.com"])
        make_recipient(group, "group@example.com")

        frappe.db.set_value("Notifire Site", "off.example.com", "enabled", 0)
        recipients, gname, used = utils.resolve_recipients("off.example.com")
        self.assertEqual((recipients, gname, used), (["fb@example.com"], fallback.name, True))

    def test_unknown_site_uses_fallback_group(self):
        fallback = make_group("FB", fallback=1)
        make_recipient(fallback, "ops@example.com")

        recipients, gname, used = utils.resolve_recipients("nowhere.example.com")
        self.assertEqual((recipients, gname, used), (["ops@example.com"], fallback.name, True))
        recipients, gname, used = utils.resolve_recipients(None)
        self.assertEqual(recipients, ["ops@example.com"])


class TestGroupOverview(FrappeTestCase):
    def test_overview_reports_effective_recipients(self):
        group = make_group("Overview", ["a.example.com", "b.example.com"])
        make_recipient(group, "scoped@example.com", applies_to=["a.example.com"])
        make_recipient(group, "default@example.com")

        data = api.group_overview(group.name)
        sites = {site["hostname"]: site for site in data["sites"]}
        self.assertEqual(sites["a.example.com"]["source"], "scoped")
        self.assertEqual(sites["a.example.com"]["recipients"], ["scoped@example.com"])
        self.assertEqual(sites["b.example.com"]["source"], "default")
        self.assertEqual(sites["b.example.com"]["recipients"], ["default@example.com"])
        self.assertIn("/api/method/notifire.api.webhook?group=overview", data["webhook_url"])

    def test_overview_warns_when_nobody_is_configured(self):
        group = make_group("Lonely", ["c.example.com"])
        data = api.group_overview(group.name)
        self.assertTrue(data["warnings"])
        self.assertEqual(data["sites"][0]["source"], "none")
