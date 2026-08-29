# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

import json
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from notifire.notifire import api
from notifire.notifire.doctype.notifire_group.notifire_group_test import make_group, make_recipient


def call_webhook(group, payload=None, secret="", raw=None):
    body = raw if raw is not None else (frappe.as_json(payload) if payload is not None else "")
    return api.handle_webhook(group=group, provided_secret=secret, raw_body=body)


class TestNotifireWebhook(FrappeTestCase):
    def test_unknown_endpoint_needs_global_secret(self):
        with self.assertRaises(frappe.AuthenticationError):
            call_webhook("nope", {"event": "Webhook Validate"}, secret="")
        with self.assertRaises(frappe.AuthenticationError):
            call_webhook("nope", {"event": "Webhook Validate"}, secret="wrong")

        settings = frappe.get_doc("Notifire Settings")
        settings.fallback_secret = "global-test-secret"
        settings.save()
        # With the global secret, the 404 is revealed instead of 401.
        with self.assertRaises(frappe.DoesNotExistError):
            call_webhook("nope", {"event": "Webhook Validate"}, secret="global-test-secret")

    def test_known_endpoint_accepts_group_and_global_secret(self):
        group = make_group("Auth", ["h.example.com"])
        group_secret = group.get_password("secret")

        self.assertEqual(call_webhook(group.slug, {"event": "Webhook Validate"}, secret=group_secret), "OK")

        settings = frappe.get_doc("Notifire Settings")
        settings.fallback_secret = "master-secret"
        settings.save()
        self.assertEqual(call_webhook(group.slug, {"event": "Webhook Validate"}, secret="master-secret"), "OK")

        with self.assertRaises(frappe.AuthenticationError):
            call_webhook(group.slug, {"event": "Webhook Validate"}, secret="bad")

    def test_payload_validation(self):
        group = make_group("Payload", ["h.example.com"])
        secret = group.get_password("secret")
        for body in ("{bad", "[1, 2]", json.dumps({"data": {}}), json.dumps({"event": "   "})):
            with self.assertRaises(frappe.ValidationError):
                call_webhook(group.slug, secret=secret, raw=body)

    def test_validate_event_logs_without_email(self):
        group = make_group("Validate", ["h.example.com"])
        secret = group.get_password("secret")
        with mock.patch("frappe.sendmail") as send:
            resp = call_webhook(group.slug, {"event": "Webhook Validate"}, secret=secret)
        self.assertEqual(resp, "OK")
        send.assert_not_called()
        logs = frappe.get_all(
            "Notifire Log", filters={"event": "Webhook Validate"}, fields=["status", "error"]
        )
        self.assertEqual(logs[0].status, "Received")
        self.assertIn("no notification sent", logs[0].error)

    def test_event_sends_notification(self):
        group = make_group("Notify", ["site.example.com"])
        make_recipient(group, "ops@example.com")
        secret = group.get_password("secret")
        payload = {
            "event": "Site Plan Change",
            "data": {"site": "site.example.com", "from_plan": "Small", "to_plan": "Large", "status": "Success"},
        }
        with mock.patch("frappe.sendmail") as send:
            resp = call_webhook(group.slug, payload, secret=secret)
        self.assertEqual(resp["status"], "ok")
        self.assertEqual(resp["notification_status"], "sent")
        send.assert_called_once()
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["recipients"], ["ops@example.com"])
        self.assertEqual(kwargs["subject"], "[Notifire] Site Plan Change - site.example.com")
        self.assertTrue(kwargs["message"].strip().lower().startswith("<!doctype html>"))

        logs = frappe.get_all(
            "Notifire Log",
            filters={"event": "Site Plan Change"},
            fields=["status", "sent_to", "site", "group", "via_fallback", "payload", "ref_name"],
        )
        self.assertEqual(len(logs), 1)
        row = logs[0]
        self.assertEqual(row.status, "Sent")
        self.assertEqual(row.sent_to, "ops@example.com")
        self.assertEqual(row.site, "site.example.com")
        self.assertEqual(row.group, group.name)
        self.assertEqual(row.via_fallback, 0)
        self.assertEqual(row.ref_name, "site.example.com")
        self.assertEqual(json.loads(row.payload)["data"]["to_plan"], "Large")

    def test_no_recipients_failed_without_email(self):
        group = make_group("Silent", ["site.example.com"])
        secret = group.get_password("secret")
        payload = {"event": "Site Status Update", "data": {"site": "site.example.com"}}
        with mock.patch("frappe.sendmail") as send:
            resp = call_webhook(group.slug, payload, secret=secret)
        self.assertEqual(resp["notification_status"], "failed")
        send.assert_not_called()
        logs = frappe.get_all("Notifire Log", filters={"event": "Site Status Update"}, fields=["status", "error"])
        self.assertEqual(logs[0].status, "Failed")
        self.assertIn("No recipients configured", logs[0].error)

    def test_siteless_event_routes_to_fallback(self):
        fallback = make_group("BenchFB", fallback=1)
        make_recipient(fallback, "fb@example.com")
        group = make_group("Direct", ["known.example.com"])
        secret = group.get_password("secret")
        payload = {"event": "Bench Deployed", "data": {"name": "bench-0019"}}
        with mock.patch("frappe.sendmail") as send:
            resp = call_webhook(group.slug, payload, secret=secret)
        self.assertEqual(resp["notification_status"], "sent")
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["recipients"], ["fb@example.com"])
        self.assertEqual(kwargs["subject"], "[Notifire] Bench Deployed - bench-0019")
        logs = frappe.get_all(
            "Notifire Log", filters={"event": "Bench Deployed"}, fields=["via_fallback", "site", "ref_name"]
        )
        self.assertEqual(logs[0].via_fallback, 1)
        self.assertEqual(logs[0].site, "")
        self.assertEqual(logs[0].ref_name, "bench-0019")

    def test_dedupe_suppresses_repeat(self):
        group = make_group("Dedupe", ["site.example.com"])
        make_recipient(group, "ops@example.com")
        secret = group.get_password("secret")
        payload = {"event": "Site Status Update", "data": {"site": "site.example.com", "status": "Broken"}}
        with mock.patch("frappe.sendmail") as send:
            self.assertEqual(call_webhook(group.slug, payload, secret=secret)["notification_status"], "sent")
            self.assertEqual(
                call_webhook(group.slug, payload, secret=secret)["notification_status"], "suppressed"
            )
        send.assert_called_once()
        suppressed = frappe.get_all("Notifire Log", filters={"status": "Suppressed"}, fields=["error"])
        self.assertEqual(len(suppressed), 1)
        self.assertIn("dedupe window", suppressed[0].error)

    def test_dedupe_isolated_by_site_and_event(self):
        group = make_group("Iso", ["a.example.com", "b.example.com"])
        make_recipient(group, "ops@example.com")
        secret = group.get_password("secret")
        with mock.patch("frappe.sendmail"):
            call_webhook(group.slug, {"event": "E", "data": {"site": "a.example.com"}}, secret=secret)
            self.assertEqual(
                call_webhook(group.slug, {"event": "E", "data": {"site": "b.example.com"}}, secret=secret)[
                    "notification_status"
                ],
                "sent",
            )
            self.assertEqual(
                call_webhook(group.slug, {"event": "F", "data": {"site": "a.example.com"}}, secret=secret)[
                    "notification_status"
                ],
                "sent",
            )

    def test_dedupe_siteless_identity_uses_ref_name(self):
        fallback = make_group("BenchDedupe", fallback=1)
        make_recipient(fallback, "fb@example.com")
        secret = fallback.get_password("secret")
        with mock.patch("frappe.sendmail"):
            call_webhook(fallback.slug, {"event": "Bench Update", "data": {"name": "bench-1"}}, secret=secret)
            self.assertEqual(
                call_webhook(fallback.slug, {"event": "Bench Update", "data": {"name": "bench-2"}}, secret=secret)[
                    "notification_status"
                ],
                "sent",
            )
            self.assertEqual(
                call_webhook(fallback.slug, {"event": "Bench Update", "data": {"name": "bench-1"}}, secret=secret)[
                    "notification_status"
                ],
                "suppressed",
            )

    def test_dedupe_window_zero_disables(self):
        settings = frappe.get_doc("Notifire Settings")
        settings.dedupe_window_minutes = 0
        settings.save()
        group = make_group("NoDedupe", ["site.example.com"])
        make_recipient(group, "ops@example.com")
        secret = group.get_password("secret")
        payload = {"event": "Site Status Update", "data": {"site": "site.example.com"}}
        with mock.patch("frappe.sendmail"):
            self.assertEqual(call_webhook(group.slug, payload, secret=secret)["notification_status"], "sent")
            self.assertEqual(call_webhook(group.slug, payload, secret=secret)["notification_status"], "sent")

    def test_failed_delivery_does_not_arm_window(self):
        group = make_group("FailArm", ["site.example.com"])
        make_recipient(group, "ops@example.com")
        secret = group.get_password("secret")
        payload = {"event": "Site Status Update", "data": {"site": "site.example.com"}}
        with mock.patch("frappe.sendmail", side_effect=Exception("SMTP down")):
            self.assertEqual(call_webhook(group.slug, payload, secret=secret)["notification_status"], "failed")
        with mock.patch("frappe.sendmail") as send:
            self.assertEqual(call_webhook(group.slug, payload, secret=secret)["notification_status"], "sent")
        send.assert_called_once()

    def test_send_failure_sanitized_in_log(self):
        group = make_group("FailLog", ["site.example.com"])
        make_recipient(group, "ops@example.com")
        secret = group.get_password("secret")
        payload = {"event": "Site Status Update", "data": {"site": "site.example.com"}}
        with mock.patch("frappe.sendmail", side_effect=Exception("Connection refused 123456")):
            call_webhook(group.slug, payload, secret=secret)
        logs = frappe.get_all("Notifire Log", filters={"status": "Failed"}, fields=["error"])
        self.assertIn("Exception: Connection refused", logs[0].error)

    def test_notifications_disabled(self):
        group = make_group("Off", ["site.example.com"])
        make_recipient(group, "ops@example.com")
        secret = group.get_password("secret")
        settings = frappe.get_doc("Notifire Settings")
        settings.enabled = 0
        settings.save()
        payload = {"event": "Site Status Update", "data": {"site": "site.example.com"}}
        with mock.patch("frappe.sendmail") as send:
            resp = call_webhook(group.slug, payload, secret=secret)
        self.assertEqual(resp["notification_status"], "skipped")
        send.assert_not_called()
