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

`after_install` seeds Notifire Settings with a global secret (disabled), strict site binding, and a 10-minute dedupe window. Logs are dropped after 30 days by Frappe's daily log clearing.

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

## Email sending

Mail goes out inside the webhook request (`now=True`), so the log status is a real delivery result. That holds the request open for the SMTP round trip, so a burst of webhooks occupies workers. Tick **Send Emails In Background** in Settings to hand mail to the queue instead — responses get fast, but you need workers running and "Sent" then means "queued".

## Dedupe window

A flapping site cycling Active → Broken → Active fires one webhook per transition. Within the window (default 10 minutes, `0` disables), repeats of the same event for the same site are logged **Suppressed** instead of emailed. Identity is event + site; site-less bench events use the object name, so two benches never suppress each other. The cutoff is computed in the site's timezone, which is what Frappe stores in `creation` — comparing against UTC would stretch or disable the window by your offset.

## Auth

`X-Webhook-Secret` is compared in constant time against the group's token. An unknown group and a wrong token take the same path and both return `401`.

A token proves *which group is calling*, not which site it may speak for, so **Strict Site Binding** (on by default) additionally requires the payload's site to be listed on that group. Without it, any group's token could forge an alert for another customer's site and reach the recipients scoped to it. If you add sites in Frappe Cloud faster than you list them here, turn it off — the events then go through and the log says which site was unlisted.

The **global secret** is a master token accepted by every group. It is **off by default**: one leaked value would forge events for every group. Turn on *Allow Global Secret* only if you need it. Both secrets are `Password` fields, so they are encrypted at rest and appear as asterisks in version history; read them with **Copy Token** / **Show Global Secret**, rotate them with the neighbouring button.

Payloads carrying their own `timestamp` are rejected if it is more than 24 hours old. That is a weak replay guard, but Frappe Cloud only sends a static shared secret, so it is the only freshness signal available.

## Tests

```bash
bench --site <site> run-tests --app notifire
```

Covers URL/token generation, site binding and the forged-site case, HTML escaping, auth, site extraction against the real Frappe Cloud payloads (including bench and deploy ids that must not be read as hostnames), ball colours, recipient matching, dedupe, and log statuses.
