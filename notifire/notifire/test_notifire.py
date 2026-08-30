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
# The live payload, which differs from the docs: doctype is Deploy Candidate
# Build, `name` is an opaque hash, and the readable id is deploy_candidate.
DEPLOY_STATUS = {
    "event": "Bench Deploy Status Update",
    "data": {
        "doctype": "Deploy Candidate Build",
        "name": "6p4ajiomvd",
        "deploy_candidate": "deploy-6453-000675",
        "group": "bench-6453",
        "status": "Running",
    },
}


def make_group(name="bench-0019", hostnames=("test465.frappe.cloud", "ytest.tanmoy.fc.frappe.dev")):
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


def call(payload, secret):
    """Drive the endpoint the way a real request does."""
    body = json.dumps(payload)
    frappe.local.request = frappe._dict(
        headers={"X-Webhook-Secret": secret},
        content_length=len(body),
        get_data=lambda as_text=True: body,
    )
    # bypass the rate-limit wrapper: it needs redis and a request ip
    return getattr(api.webhook, "__wrapped__", api.webhook)()


def token_of(group):
    return group.get_password("token")


class TestNotifire(FrappeTestCase):
    def tearDown(self):
        # FrappeTestCase rolls the database back, but the Single is cached and
        # frappe.local.request is a fake this module installed.
        frappe.clear_cache(doctype="Notifire Settings")
        frappe.local.request = None
        super().tearDown()

    def test_url_and_token_are_generated(self):
        group = make_group()
        # Frappe Cloud rejects an endpoint URL with a query string
        self.assertTrue(group.webhook_url.endswith("/api/method/notifire.api.webhook"))
        self.assertNotIn("?", group.webhook_url)
        self.assertEqual(len(token_of(group)), 48)

    def test_token_identifies_the_group(self):
        first = make_group("bench-0019", ["test465.frappe.cloud"])
        second = make_group("bench-0042", ["other.frappe.cloud"])
        make_recipient("ops@example.com")

        with mock.patch("frappe.sendmail"):
            call({"event": "Site Plan Change", "data": {"site": "other.frappe.cloud"}}, token_of(second))
        log = frappe.get_all(
            "Notifire Log", filters={"site": "other.frappe.cloud"}, fields=["group"]
        )[0]
        self.assertEqual(log.group, second.name)
        self.assertNotEqual(log.group, first.name)

    def test_bad_token_is_rejected(self):
        group = make_group()
        with self.assertRaises(frappe.AuthenticationError):
            call(PLAN_CHANGE, "wrong")
        with self.assertRaises(frappe.AuthenticationError):
            call(PLAN_CHANGE, "also-wrong")

    def test_global_secret_also_works(self):
        group = make_group()
        settings = frappe.get_doc("Notifire Settings")
        settings.webhook_secret = "master-key"
        settings.allow_global_secret = 1
        settings.save()
        frappe.clear_cache(doctype="Notifire Settings")
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail"):
            self.assertEqual(call(PLAN_CHANGE, "master-key"), "OK")

    def test_validate_event_sends_no_email(self):
        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            self.assertEqual(call({"event": "Webhook Validate", "data": {}}, token_of(group)), "OK")
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
            call(PLAN_CHANGE, token_of(group))

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
            call(BENCH_STATUS, token_of(group))
        self.assertEqual(send.call_args.kwargs["recipients"], ["ops@example.com"])
        log = frappe.get_all(
            "Notifire Log", filters={"event": "Bench Status Update"}, fields=["site", "reference"]
        )[0]
        self.assertEqual(log.site, "")
        self.assertEqual(log.reference, "bench-0019-000059-f2-london")

    def test_no_recipients_is_logged_as_failed(self):
        group = make_group()
        with mock.patch("frappe.sendmail") as send:
            call(PLAN_CHANGE, token_of(group))
        send.assert_not_called()
        log = frappe.get_all("Notifire Log", filters={"status": "Failed"}, fields=["error"])[0]
        self.assertIn("No recipient", log.error)

    def test_dedupe_suppresses_the_repeat(self):
        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            call(SITE_STATUS, token_of(group))
            call(SITE_STATUS, token_of(group))
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
            call(SITE_STATUS, token_of(group))
            call(SITE_STATUS, token_of(group))
        self.assertEqual(send.call_count, 2)

    def test_site_must_belong_to_the_calling_group(self):
        """A token proves which group is calling, not which site it may speak for."""
        group = make_group("bench-0019", ["test465.frappe.cloud"])
        make_recipient("ops@example.com")
        forged = {"event": "Site Plan Change", "data": {"site": "othercustomer.frappe.cloud"}}

        with mock.patch("frappe.sendmail") as send:
            with self.assertRaises(frappe.AuthenticationError):
                call(forged, token_of(group))
        send.assert_not_called()
        log = frappe.get_all(
            "Notifire Log", filters={"site": "othercustomer.frappe.cloud"}, fields=["status", "error"]
        )[0]
        self.assertEqual(log.status, "Failed")
        self.assertIn("not listed", log.error)

    def test_site_binding_can_be_turned_off(self):
        settings = frappe.get_doc("Notifire Settings")
        settings.strict_site_binding = 0
        settings.save()
        frappe.clear_cache(doctype="Notifire Settings")

        group = make_group("bench-0019", ["test465.frappe.cloud"])
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            call({"event": "Site Plan Change", "data": {"site": "other.frappe.cloud"}}, token_of(group))
        send.assert_called_once()

    def test_sendmail_is_called_with_arguments_it_accepts(self):
        """Mocking frappe.sendmail hides a wrong kwarg until it hits production."""
        import inspect

        group = make_group()
        make_recipient("ops@example.com")
        with mock.patch("frappe.sendmail") as send:
            call(PLAN_CHANGE, token_of(group))

        accepted = inspect.signature(frappe.sendmail).parameters
        takes_kwargs = any(p.kind == p.VAR_KEYWORD for p in accepted.values())
        for name in send.call_args.kwargs:
            self.assertTrue(
                takes_kwargs or name in accepted,
                "frappe.sendmail() does not accept {0}".format(name),
            )

    def test_payload_html_is_escaped(self):
        group = make_group()
        make_recipient("ops@example.com")
        payload = {
            "event": "Site Status Update",
            "data": {
                "host_name": "test465.frappe.cloud",
                "status": "<a href='https://evil.example'>Restore your site</a>",
            },
        }
        with mock.patch("frappe.sendmail") as send:
            call(payload, token_of(group))

        message = send.call_args.kwargs["message"]
        self.assertNotIn("<a href", message)
        self.assertIn("&lt;a href", message)

    def test_hostname_cannot_be_claimed_by_two_groups(self):
        make_group("bench-0019", ["shared.frappe.cloud"])
        with self.assertRaises(frappe.ValidationError):
            make_group("bench-0042", ["shared.frappe.cloud"])

    def test_stale_event_is_rejected(self):
        group = make_group()
        old = {
            "event": "Site Plan Change",
            "data": {"site": "test465.frappe.cloud", "timestamp": "2020-01-01 00:00:00"},
        }
        with self.assertRaises(frappe.ValidationError):
            call(old, token_of(group))

    def test_global_secret_is_off_by_default(self):
        group = make_group()
        settings = frappe.get_doc("Notifire Settings")
        settings.webhook_secret = "master-key"
        settings.allow_global_secret = 0
        settings.save()
        frappe.clear_cache(doctype="Notifire Settings")
        with self.assertRaises(frappe.AuthenticationError):
            call(PLAN_CHANGE, "master-key")

    def test_deploy_event_reaches_the_groups_scoped_recipients(self):
        """A deploy event carries no site, but it belongs to the calling group."""
        group = make_group("magicbus", ["test465.frappe.cloud"])
        make_recipient("ops@example.com", ["test465.frappe.cloud"])

        with mock.patch("frappe.sendmail") as send:
            call(DEPLOY_STATUS, token_of(group))
        self.assertEqual(send.call_args.kwargs["recipients"], ["ops@example.com"])

        log = frappe.get_all(
            "Notifire Log",
            filters={"event": "Bench Deploy Status Update"},
            fields=["status", "reference", "event_status"],
        )[0]
        self.assertEqual(log.status, "Sent")
        # not the opaque hash from `name`
        self.assertEqual(log.reference, "deploy-6453-000675")
        self.assertEqual(log.event_status, "Running")

    def test_deploy_event_skips_recipients_of_another_group(self):
        make_group("magicbus", ["test465.frappe.cloud"])
        other = make_group("bench-0042", ["other.frappe.cloud"])
        make_recipient("ops@example.com", ["test465.frappe.cloud"])

        with mock.patch("frappe.sendmail") as send:
            call(DEPLOY_STATUS, token_of(other))
        send.assert_not_called()

    def test_build_progress_is_not_deduped_away(self):
        group = make_group("magicbus", ["test465.frappe.cloud"])
        make_recipient("ops@example.com")

        def build(status):
            payload = json.loads(json.dumps(DEPLOY_STATUS))
            payload["data"]["status"] = status
            return payload

        with mock.patch("frappe.sendmail") as send:
            call(build("Pending"), token_of(group))
            call(build("Preparing"), token_of(group))
            call(build("Running"), token_of(group))
            call(build("Running"), token_of(group))  # a real repeat

        self.assertEqual(send.call_count, 3)
        self.assertEqual(frappe.db.count("Notifire Log", {"status": "Suppressed"}), 1)

    def test_bad_payload_is_rejected(self):
        group = make_group()
        for body in ({"data": {}}, {"event": "  "}):
            with self.assertRaises(frappe.ValidationError):
                call(body, token_of(group))
