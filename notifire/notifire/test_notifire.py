# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from notifire import api, utils

# Real payloads from the Frappe Cloud webhook docs.
PLAN_CHANGE = {
    "event": "Site Plan Change",
    "data": {
        "doctype": "Site Plan Change",
        "name": "368704046d",
        "from_plan": "USD 10",
        "to_plan": "USD 25",
        "type": "Upgrade",
        "site": "test465.frappe.cloud",
        "timestamp": "2024-09-24 11:29:41.596639",
    },
}
SITE_STATUS = {
    "event": "Site Status Update",
    "data": {
        "doctype": "Site",
        "name": "ytest.tanmoy.fc.frappe.dev",
        "status": "Active",
        "group": "bench-0008",
        "host_name": "ytest.tanmoy.fc.frappe.dev",
        "cluster": "Default",
    },
}
BENCH_STATUS = {
    "event": "Bench Status Update",
    "data": {
        "doctype": "Bench",
        "name": "bench-0019-000059-f2-london",
        "group": "bench-0019",
        "status": "Pending",
        "cluster": "London",
    },
}
DEPLOY_STATUS = {
    "event": "Bench Deploy Status Update",
    "data": {"doctype": "Deploy Candidate", "name": "deploy-0019-000059", "status": "Success"},
}


def make_group(name="bench-0019", hostnames=("test465.frappe.cloud",)):
    return frappe.get_doc({
        "doctype": "Bench Group",
        "__newname": name,
        "hostnames": [{"hostname": h} for h in hostnames],
    }).insert()


def make_recipient(email, hostnames=None):
    return frappe.get_doc({
        "doctype": "Notifire Recipient",
        "email": email,
        "hostnames": [{"hostname": h} for h in (hostnames or [])],
    }).insert()


def call(group, payload, secret):
    """Drive the endpoint the way a real request does."""
    frappe.local.request = frappe._dict(
        headers={"X-Webhook-Secret": secret},
        get_data=lambda as_text=True: json.dumps(payload),
    )
    return api.webhook(group=group)


class TestNotifire(FrappeTestCase):
    def test_url_and_token_are_generated(self):
        group = make_group()
        self.assertTrue(group.webhook_url.endswith("/api/method/notifire.api.webhook?group=bench-0019"))
        self.assertEqual(len(group.token), 48)

    def test_bad_token_is_rejected(self):
        group = make_group()
        with self.assertRaises(frappe.AuthenticationError):
            call(group.name, PLAN_CHANGE, "wrong")
        with self.assertRaises(frappe.AuthenticationError):
            call("no-such-group", PLAN_CHANGE, group.token)

    def test_global_secret_also_works(self):
        group = make_group()
        settings = frappe.get_doc("Notifire Settings")
        settings.webhook_secret = "master-key"
        settings.save()
        frappe.clear_cache(doctype="Notifire Settings")
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail"):
            self.assertEqual(call(group.name, PLAN_CHANGE, "master-key"), "OK")

    def test_validate_event_sends_no_email(self):
        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            self.assertEqual(call(group.name, {"event": "Webhook Validate", "data": {}}, group.token), "OK")
        send.assert_not_called()

    def test_site_extraction_ignores_bench_ids(self):
        self.assertEqual(utils.extract_site(PLAN_CHANGE), "test465.frappe.cloud")
        self.assertEqual(utils.extract_site(SITE_STATUS), "ytest.tanmoy.fc.frappe.dev")
        self.assertIsNone(utils.extract_site(BENCH_STATUS))
        self.assertIsNone(utils.extract_site(DEPLOY_STATUS))

    def test_ball_colours(self):
        self.assertEqual(utils.status_ball("Active"), "\U0001F7E2")
        self.assertEqual(utils.status_ball("Broken"), "\U0001F534")
        self.assertEqual(utils.status_ball("Pending"), "\U0001F7E1")
        self.assertEqual(utils.status_ball(None), "")

    def test_scoped_and_catch_all_recipients(self):
        make_group(hostnames=["test465.frappe.cloud", "other.frappe.cloud"])
        make_recipient("scoped@example.com", ["test465.frappe.cloud"])
        make_recipient("all@example.com")

        self.assertEqual(
            utils.find_recipients("test465.frappe.cloud"), ["scoped@example.com", "all@example.com"]
        )
        self.assertEqual(utils.find_recipients("other.frappe.cloud"), ["all@example.com"])
        # bench/deploy events have no site: only catch-all recipients get them
        self.assertEqual(utils.find_recipients(None), ["all@example.com"])

    def test_unknown_hostname_rejected_on_recipient(self):
        make_group()
        with self.assertRaises(frappe.ValidationError):
            make_recipient("x@example.com", ["ghost.frappe.cloud"])

    def test_event_is_emailed_and_logged(self):
        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            call(group.name, PLAN_CHANGE, group.token)

        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["recipients"], ["ops@example.com"])
        self.assertIn("Site Plan Change - test465.frappe.cloud", kwargs["subject"])

        log = frappe.get_all(
            "Notifire Log", filters={"event": "Site Plan Change"}, fields=["status", "site", "recipients"]
        )[0]
        self.assertEqual(log.status, "Sent")
        self.assertEqual(log.site, "test465.frappe.cloud")
        self.assertEqual(log.recipients, "ops@example.com")

    def test_bench_event_reaches_catch_all(self):
        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            call(group.name, BENCH_STATUS, group.token)
        self.assertEqual(send.call_args.kwargs["recipients"], ["ops@example.com"])
        log = frappe.get_all(
            "Notifire Log", filters={"event": "Bench Status Update"}, fields=["site", "reference"]
        )[0]
        self.assertEqual(log.site, "")
        self.assertEqual(log.reference, "bench-0019-000059-f2-london")

    def test_no_recipients_is_logged_as_failed(self):
        group = make_group()
        with mock.patch("frappe.sendmail") as send:
            call(group.name, PLAN_CHANGE, group.token)
        send.assert_not_called()
        log = frappe.get_all("Notifire Log", filters={"status": "Failed"}, fields=["error"])[0]
        self.assertIn("No recipient", log.error)

    def test_dedupe_suppresses_the_repeat(self):
        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            call(group.name, SITE_STATUS, group.token)
            call(group.name, SITE_STATUS, group.token)
        send.assert_called_once()
        self.assertEqual(frappe.db.count("Notifire Log", {"status": "Suppressed"}), 1)

    def test_dedupe_window_zero_disables_it(self):
        settings = frappe.get_doc("Notifire Settings")
        settings.dedupe_window_minutes = 0
        settings.save()
        frappe.clear_cache(doctype="Notifire Settings")

        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            call(group.name, SITE_STATUS, group.token)
            call(group.name, SITE_STATUS, group.token)
        self.assertEqual(send.call_count, 2)

    def test_bad_payload_is_rejected(self):
        group = make_group()
        for body in ({"data": {}}, {"event": "  "}):
            with self.assertRaises(frappe.ValidationError):
                call(group.name, body, group.token)
