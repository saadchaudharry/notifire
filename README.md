# Notifire — Frappe custom app

Frappe Cloud webhook receiver + notification routing, re-implemented **natively as a Frappe custom app**. There is no custom web UI to maintain: every screen (groups, recipients, logs, settings) is the Frappe **Desk** UI, with list search, filters, sorting and role permissions for free.

The app receives Frappe Cloud webhooks (site plan changes, site status updates, bench/deploy events, ...), matches the webhook's site hostname against **Notification Groups**, and emails the right **Recipients** — with per-endpoint secrets, a global fallback secret, an anti email-storm **dedupe window**, and a full audit trail in **Notifire Log**.

This is a 1:1 port of the earlier Django + SQLite edition (same behaviour, same email copy, same security posture). The Django project can be retired once this app is installed.

---

## Feature parity with the Django edition

| Django edition                        | Frappe app                                            |
| ------------------------------------- | ----------------------------------------------------- |
| `NotificationGroup` + admin           | **Notifire Group** DocType (Desk form + list)         |
| `SiteHostname` rows                   | **Notifire Group Hostname** child table (one per row) |
| `Email` + "Applies to" multiselect    | **Notifire Recipient** + **Notifire Recipient Scope** (Table MultiSelect chips) |
| `NotificationLog` + list filters      | **Notifire Log** DocType with status colour indicators |
| key/value `Setting` + settings page   | **Notifire Settings** (single DocType)                |
| `WEBHOOK_SECRET` env var              | Global fallback secret (encrypted, auto-generated at install) |
| per-site webhook key                  | Per-group secret (encrypted, auto-generated, rotatable from the form) |
| `POST /notify/<slug>`                 | `POST /api/method/notifire.api.webhook?group=<slug>`  |
| dedupe window (10 min default)        | Same, configurable in Notifire Settings              |
| red/yellow/green status balls         | Same emoji in email + log form headline; list rows get colour indicators |
| email template                        | Same copy/layout, rendered with Jinja                 |
| custom Django UI (login, pages, CSS)  | **Not required** — Desk handles everything            |

---

## Requirements

- Frappe Framework **v14 or v15** (no ERPNext or other apps required)
- A **central receiver site** (the one that installs this app) reachable by every monitored site
- An outgoing **Email Account** configured on that site (e.g. Gmail SMTP with an app password)

> The receiver itself should be one dedicated Frappe site (a hub). Monitored sites do **not** install this app — they just POST webhooks to the hub.

## Install

From the zip (or a git URL), on the receiver bench:

```bash
# unzip / clone so that the folder contains pyproject.toml + notifire/
bench get-app /path/to/notifire          # or: bench get-app <git-url>
bench --site <receiver-site> install-app notifire
bench --site <receiver-site> migrate
bench restart
```

`after_install` seeds **Notifire Settings** with a 48-char global fallback secret and sane defaults. No background-worker dependency for notifications: mail is sent synchronously (`now=True`), so log statuses always reflect real delivery attempts.

## Setup (all inside Desk)

1. **Outgoing email** — set up an Email Account on the receiver site (e.g. Gmail SMTP). Gmail caps ~500 mails/day; keep that in mind and let the dedupe window help (below).
2. **Notifire Group** — create a group (e.g. "Pre Prod Ops"). The **webhook secret is generated automatically** on save. Add one **hostname row per Frappe Cloud site** (multiple benches/sites of one account are fine). Hostnames are unique across all groups, so every site routes to exactly one group.
3. **Recipients** — add recipient rows for the group:
   - **Applies to** empty → default recipient for every hostname of the group.
   - **Applies to** set to one or more hostnames (multi-select chips) → receives only those hostnames' events and **replaces** the group defaults for them.
4. **Fallback group** (optional) — tick *Fallback group* on exactly one group; it receives webhooks whose site is unknown or absent (e.g. bench/deploy events, which carry no site hostname).

### Point the webhooks at the receiver

On each monitored Frappe Cloud site, configure the webhook (Frappe Cloud dashboard → site → Webhooks, or a Server Script / `frappe.outgoing_email` style integration):

```
URL:    https://<receiver-site>/api/method/notifire.api.webhook?group=<slug>
Method: POST
Header: X-Webhook-Secret: <group secret — or the global fallback secret>
```

The **Webhook Validate** event is answered with `200 "OK"` and logged (Received) without sending any email — use it to test the wiring. A quick curl:

```bash
curl -X POST "https://<receiver-site>/api/method/notifire.api.webhook?group=pre-prod-ops" \
     -H "X-Webhook-Secret: <secret>" \
     -H "Content-Type: application/json" \
     -d '{"event": "Webhook Validate"}'
```

## Authentication rules (same posture as the Django edition)

- `X-Webhook-Secret` is compared in **constant time**; comparisons **fail closed**.
- A known endpoint accepts its **own secret** or the **global fallback secret**.
- An **unknown/disabled** endpoint first requires the **global** secret before the 404 is revealed (no free slug enumeration for strangers): wrong/missing secret → `401`, valid global secret → `404`.
- Secrets live encrypted (Password fields) and never appear in logs, emails or responses.
- Rotate a group secret with the **Rotate Secret** button on its form — the old secret dies immediately. The webhook URL is shown in the form headline with a **Copy Webhook URL** button.

## Email-storm guard (dedupe window)

A flapping site cycling Active → Broken → Active fires one webhook (and one email) per transition — enough to burn Gmail's ~500/day cap and silently stop all notifications. Within the configured **dedupe window** (Notifire Settings, default **10 minutes**, `0` disables, max 1440) only the **first email per event + site** is sent; repeats are logged with status **Suppressed** (blue indicator) and a note pointing at the last Sent time. Identity is `event + group + site`; site-less bench/deploy events use the object reference instead, so two different benches never suppress each other. The window is deliberately checked *after* the recipients guard, so undeliverable events keep failing loudly instead of being swallowed.

## Logs

Every webhook (valid or not) is recorded in **Notifire Log** with event, site, reference, resolved group, via-fallback flag, recipients, the full JSON payload, and a note/error field. Statuses get colour indicators in the list (Sent green, Received orange, Failed red, Suppressed blue); the log form shows the traffic-light ball derived from the payload's `data.status`. Filter/search everything from the standard list view.

## Tests

On a bench (with the app installed on a test site):

```bash
bench --site <test-site> run-tests --app notifire
```

~27 tests cover: secret auto-generation and slugs, single-fallback enforcement, hostname uniqueness (in-group + cross-group), site extraction priorities, recipient scoping/precedence/case rules, endpoint auth (401/404 split, global vs per-group secrets), payload validation, Webhook Validate, send + log assertions, fallback routing, dedupe suppression/isolation/disabling, failed-delivery arming rules, and notification-disabled mode.

## Notes

- **Migrating from the Django edition**: recreate your groups/recipients (they are few), then point each monitored site's webhook to the new URL. The header name (`X-Webhook-Secret`) and payload handling are unchanged; the old `/notify/<slug>` endpoints simply retire with the Django app.
- Descriptive HTTP quirks are inherited on purpose: invalid payloads return Frappe's `ValidationError` (HTTP 417) instead of the old 400 — still non-200, still logged.
- Only **System Manager** sees the DocTypes; add roles on each DocType if you want to delegate.
- Uninstalling removes the DocTypes and their data (export your logs first if you need them).
