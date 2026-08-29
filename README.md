# Notifire — Frappe custom app

Frappe Cloud webhook receiver and notification routing, native to Frappe. There is no custom web UI to maintain: every screen is the Frappe **Desk**, with list search, filters, sorting and role permissions for free.

The app receives Frappe Cloud webhooks (site plan changes, site status updates, bench/deploy events, …), matches the payload's site hostname against a **Notifire Site**, and emails the recipients of the group that hostname belongs to — with per-endpoint secrets, a global fallback secret, an anti email-storm **dedupe window**, and a full audit trail in **Notifire Log**.

---

## The model in three nouns

| Noun                  | What it is                                                                  |
| --------------------- | --------------------------------------------------------------------------- |
| **Notifire Group**    | One webhook endpoint: a slug, a secret, and the recipients behind it.        |
| **Notifire Site**     | One Frappe Cloud hostname, routed to exactly one group. The docname *is* the hostname, so a site can never belong to two groups. |
| **Notifire Recipient**| An email address in a group. It covers every hostname of the group by default, or only the hostnames you select. |

Plus **Notifire Log** (every request, valid or not) and **Notifire Settings** (delivery, dedupe window, global secret).

### The one routing rule worth memorizing

A hostname with its **own** selected recipients uses only those. The group's default recipients are skipped for that hostname. Every recipient form shows this live: it lists the hostnames the address will actually receive, and the ones it will be skipped for, with the addresses that displaced it.

---

## Requirements

- Frappe Framework **v14 or v15** (no ERPNext or other apps required)
- A **central receiver site** (the one that installs this app), reachable by every monitored site
- An enabled default outgoing **Email Account** on that site

> The receiver is one dedicated Frappe site (a hub). Monitored sites do **not** install this app — they just POST webhooks to the hub.

## Install

```bash
bench get-app /path/to/notifire          # or: bench get-app <git-url>
bench --site <receiver-site> install-app notifire
bench --site <receiver-site> migrate
bench restart
```

`after_install` seeds **Notifire Settings** with a 48-char global fallback secret and sane defaults. Notifications are sent synchronously (`now=True`), so log statuses always reflect a real delivery attempt — no background worker required.

### Upgrading from the child-table version

Earlier builds kept hostnames in a child table on Notifire Group. `bench migrate` runs `notifire.patches.v1_1.migrate_hostnames_to_sites`, which turns every child row into a Notifire Site with the same hostname and group, backfills the new `Receives events for` mode on recipients, refreshes the per-group hostname counter, and drops the obsolete child DocType. Recipient scopes keep pointing at the same hostname strings, so routing is unchanged. The patch is safe to re-run.

## Setup

Open the **Notifire** workspace. It has shortcuts, link cards, and the first-run checklist:

1. **Outgoing email** — set up an Email Account on the receiver site. Gmail caps around 500 mails/day; the dedupe window below exists partly for that reason.
2. **Notifire Group** — create a group (e.g. "Pre Prod Ops"). The webhook secret is generated on save.
3. **Hostnames** — on the group form, hit **Add Hostnames** and paste your sites. One per line, or commas — pasted `https://…/app` URLs and ports are cleaned up for you. Anything that is not a hostname (bench ids, typos) is reported back per entry instead of failing the batch, and a hostname already owned by another group is named as such, with an option to move it.
4. **Recipients** — **Add Recipient** on the same form. Leave *Receives events for* on **All sites in this group** for a default address, or switch it to **Only selected sites** and pick hostnames from the dropdown (only that group's hostnames are offered).
5. **Fallback group** (optional) — tick *Fallback Group* on exactly one group. It catches webhooks whose site is unknown or absent, which is every bench and deploy event.

### Point the webhooks at the receiver

The group form shows the exact URL with a copy button, a **Show Secret** button, and **Copy test curl**. On each monitored Frappe Cloud site:

```
URL:    https://<receiver-site>/api/method/notifire.api.webhook?group=<slug>
Method: POST
Header: X-Webhook-Secret: <group secret — or the global fallback secret>
```

A **Webhook Validate** event is answered with `200 "OK"` and logged (Received) without sending mail — use it to test the wiring:

```bash
curl -X POST "https://<receiver-site>/api/method/notifire.api.webhook?group=pre-prod-ops" \
     -H "X-Webhook-Secret: <secret>" \
     -H "Content-Type: application/json" \
     -d '{"event": "Webhook Validate"}'
```

`notifire.notifire.api.webhook` resolves to the same endpoint, so senders configured with the long path keep working.

## Authentication

- `X-Webhook-Secret` is compared in **constant time**, and comparisons **fail closed**.
- A known endpoint accepts its **own secret** or the **global fallback secret**.
- An **unknown or disabled** endpoint requires the **global** secret before the 404 is revealed, so strangers cannot enumerate slugs: wrong/missing secret → `401`, valid global secret → `404`.
- Secrets are stored encrypted and never appear in logs, emails or webhook responses. **Show Secret** on the group form reveals it to a user who already has write access (and could rotate it anyway); **Rotate Secret** replaces it, and the old one dies immediately.

## Email-storm guard

A flapping site cycling Active → Broken → Active fires one webhook, and one email, per transition — enough to burn a daily send quota and silently stop every other notification. Within the **dedupe window** (Notifire Settings, default **10 minutes**, `0` disables, max 1440) only the first email per event + site goes out; repeats are logged **Suppressed** with a note pointing at the last Sent time. Identity is `event + group + site`; site-less bench/deploy events use the object reference instead, so two benches never suppress each other. The window is checked *after* the recipients guard, so undeliverable events keep failing loudly instead of being swallowed.

## Logs

Every webhook is recorded with event, site, reference, resolved group, via-fallback flag, recipients, the full payload, and a note/error field. The list colours each status (Sent green, Received orange, Failed red, Suppressed blue) and falls back to the object reference in the Site column for bench events. A failed or suppressed entry gets a **Send Now** button: it re-resolves recipients against the *current* configuration and retries immediately, ignoring the dedupe window — fix the routing, then press it.

**Notifire Settings** carries a health panel: enabled groups, hostnames, recipients, sent and failed in the last 24 hours, plus setup problems (no outgoing email account, no fallback group, notifications turned off). **Send Test Email** pushes a sample notification through the real delivery path.

## Tests

```bash
bench --site <test-site> run-tests --app notifire
```

Coverage: secret generation and slugs, single-fallback enforcement, hostname normalization and rejection of bench ids, cross-group uniqueness, per-group site counters, scope cleanup when a hostname is deleted or moved, site extraction priorities, recipient scoping/precedence/case rules and cross-group scope rejection, the bulk hostname mapper (cleanup, skips, moves), endpoint auth (401/404 split, global vs per-group secrets), payload validation, Webhook Validate, send + log assertions, fallback routing, dedupe suppression/isolation/disabling, failed-delivery arming rules, resend behaviour, and notification-disabled mode.

## Notes

- Only **System Manager** sees the DocTypes; add roles on each DocType to delegate.
- Invalid payloads return Frappe's `ValidationError` (HTTP 417) rather than a 400 — still non-200, still logged.
- Deleting a group is blocked while hostnames still route to it (they usually need moving, not deleting). Its recipients are removed with it; logs are kept and simply unlinked.
- Uninstalling removes the DocTypes and their data — export your logs first if you need them.
