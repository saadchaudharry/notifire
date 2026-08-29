# Notifire

Frappe Cloud webhooks in, email out. Four DocTypes, one endpoint, no background workers.

## How it works

| DocType             | What it is                                                                                   |
| ------------------- | -------------------------------------------------------------------------------------------- |
| **Bench Group**     | One Frappe Cloud webhook. Name it like your bench group (`bench-0019`); the URL and token are generated on save. Its child table lists the site hostnames under it. |
| **Notifire Recipient** | An email address, plus a hostname table. Empty table = receives everything.               |
| **Notifire Log**    | Every request, with status, payload and the traffic-light ball.                                |
| **Notifire Settings** | On/off, subject prefix, from address, dedupe window, global secret.                          |

Routing is one rule: **a recipient with hostnames listed gets only those sites; a recipient with an empty list gets everything.** Bench and deploy events carry no site hostname, so the empty-list recipients are the ones who receive them.

## Install

```bash
bench get-app https://github.com/saadchaudharry/notifire
bench --site <site> install-app notifire
bench --site <site> migrate
```

`after_install` seeds Notifire Settings with a global secret and a 10-minute dedupe window.

## Setup

1. Make sure the site has a default outgoing **Email Account**.
2. Create a **Bench Group** named after your Frappe Cloud bench group, and list its site hostnames.
3. Add **Recipients**. Leave the hostname table empty for someone who should get everything.
4. In Frappe Cloud → Developer Settings → Add Webhook, paste the **Webhook URL** and the **Token** (as the secret), pick your events, then press **Validate Webhook** and **Activate**.

The `Webhook Validate` event answers `OK` and is logged without emailing anyone, so validation never spams your team.

Test it by hand:

```bash
curl -X POST "https://<site>/api/method/notifire.api.webhook?group=bench-0019" \
     -H "X-Webhook-Secret: <token>" \
     -H "Content-Type: application/json" \
     -d '{"event": "Webhook Validate", "data": {}}'
```

## Status balls

Emails and the log form show a ball based on `data.status`: 🟢 for active/success/deployed, 🔴 for broken/failed/suspended, 🟡 for anything in progress or unrecognized (pending, installing, updating, …). Bench deploys run Draft → Scheduled → Pending → Preparing → Running → Success, so most of that chain is yellow until the end.

## Dedupe window

A flapping site cycling Active → Broken → Active fires one webhook per transition. Within the window (default 10 minutes, `0` disables), repeats of the same event for the same site are logged **Suppressed** instead of emailed. Identity is event + site; site-less bench events use the object name, so two benches never suppress each other.

## Auth

`X-Webhook-Secret` is compared in constant time against the group's token or the global secret. An unknown group and a wrong token both return `401`, so group names cannot be probed. Rotate a token with **Regenerate Token** on the group form, then update it in Frappe Cloud.

## Tests

```bash
bench --site <site> run-tests --app notifire
```

Covers URL/token generation, auth, site extraction against the real Frappe Cloud payloads (including bench and deploy ids that must not be read as hostnames), ball colours, recipient matching, dedupe, and log statuses.
