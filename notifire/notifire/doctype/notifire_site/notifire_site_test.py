# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import frappe
from frappe.tests.utils import FrappeTestCase

from notifire.notifire import api, utils
from notifire.notifire.doctype.notifire_group.notifire_group_test import make_group, make_recipient


class TestNotifireSite(FrappeTestCase):
    def test_hostname_is_the_docname_and_lowercased(self):
        group = make_group("Sites")
        doc = frappe.get_doc(
            {"doctype": "Notifire Site", "hostname": "  Test465.Frappe.Cloud  ", "group": group.name}
        ).insert()
        self.assertEqual(doc.name, "test465.frappe.cloud")
        self.assertEqual(doc.hostname, "test465.frappe.cloud")

    def test_bench_ids_rejected(self):
        group = make_group("BadHosts")
        for bad in ("bench-0019-000059-f2-london", "368704046d", "not a host"):
            with self.assertRaises(frappe.ValidationError):
                frappe.get_doc(
                    {"doctype": "Notifire Site", "hostname": bad, "group": group.name}
                ).insert()

    def test_site_count_tracks_group(self):
        group = make_group("Counted", ["a.example.com", "b.example.com"])
        self.assertEqual(frappe.db.get_value("Notifire Group", group.name, "site_count"), 2)
        frappe.delete_doc("Notifire Site", "a.example.com")
        self.assertEqual(frappe.db.get_value("Notifire Group", group.name, "site_count"), 1)

    def test_deleting_a_site_clears_recipient_scopes(self):
        group = make_group("Cleanup", ["a.example.com", "b.example.com"])
        recipient = make_recipient(group, "x@example.com", applies_to=["a.example.com", "b.example.com"])
        frappe.delete_doc("Notifire Site", "a.example.com")
        recipient.reload()
        self.assertEqual([row.hostname for row in recipient.get("applies_to")], ["b.example.com"])

    def test_last_scope_removal_reverts_to_group_default(self):
        group = make_group("RevertMode", ["only.example.com"])
        recipient = make_recipient(group, "x@example.com", applies_to=["only.example.com"])
        frappe.delete_doc("Notifire Site", "only.example.com")
        self.assertEqual(
            frappe.db.get_value("Notifire Recipient", recipient.name, "scope_mode"),
            "All sites in this group",
        )


class TestHostnameMapper(FrappeTestCase):
    def test_bulk_add_cleans_and_reports(self):
        group = make_group("Bulk")
        result = api.add_hostnames(
            group.name,
            "https://one.frappe.cloud/app\n TWO.frappe.cloud , three.frappe.cloud\nbench-0019",
        )
        self.assertEqual(
            sorted(result["added"]),
            ["one.frappe.cloud", "three.frappe.cloud", "two.frappe.cloud"],
        )
        self.assertEqual(len(result["skipped"]), 1)
        self.assertEqual(result["skipped"][0]["hostname"], "bench-0019")

    def test_bulk_add_skips_hostnames_owned_elsewhere(self):
        first = make_group("Owner", ["taken.example.com"])
        second = make_group("Other")
        result = api.add_hostnames(second.name, "taken.example.com")
        self.assertEqual(result["added"], [])
        self.assertIn(first.name, result["skipped"][0]["reason"])

    def test_bulk_add_can_move_hostnames(self):
        first = make_group("MoveFrom", ["moving.example.com"])
        make_recipient(first, "old@example.com", applies_to=["moving.example.com"])
        second = make_group("MoveTo")

        result = api.add_hostnames(second.name, "moving.example.com", move_existing=1)
        self.assertEqual(result["moved"], ["moving.example.com"])
        self.assertEqual(
            frappe.db.get_value("Notifire Site", "moving.example.com", "group"), second.name
        )
        # The old group's scoped recipient must not keep claiming the site.
        self.assertEqual(
            frappe.db.count(
                "Notifire Recipient Scope",
                {"parenttype": "Notifire Recipient", "hostname": "moving.example.com"},
            ),
            0,
        )

    def test_remove_hostname_requires_the_right_group(self):
        first = make_group("RemoveOwner", ["r.example.com"])
        second = make_group("RemoveOther")
        with self.assertRaises(frappe.ValidationError):
            api.remove_hostname(second.name, "r.example.com")
        api.remove_hostname(first.name, "r.example.com")
        self.assertFalse(frappe.db.exists("Notifire Site", "r.example.com"))

    def test_rotated_secret_replaces_the_old_one(self):
        group = make_group("Rotate")
        old = group.get_password("secret")
        new = api.rotate_group_secret(group.name)["secret"]
        self.assertNotEqual(old, new)
        self.assertEqual(api.get_group_secret(group.name)["secret"], new)
        self.assertFalse(utils.is_valid_secret(old, group_secret=new))
