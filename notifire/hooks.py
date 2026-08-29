app_name = "notifire"
app_title = "Notifire"
app_publisher = "Notifire contributors"
app_description = "Frappe Cloud webhook receiver: route site and bench events to notification groups, with email-storm dedupe."
app_email = "support@example.com"
app_license = "mit"

# Runs on plain Frappe v14+ (no ERPNext or other apps required).
required_apps = []

after_install = "notifire.install.after_install"

# Webhook endpoint (guest, X-Webhook-Secret authenticated):
#   POST /api/method/notifire.api.webhook?group=<slug>
#
# No scheduler events and no doc_events: everything happens inside the
# webhook request, so a plain `bench serve` (or a normal production bench)
# handles the whole flow. Emails are sent synchronously (now=True) so the
# Notifire Log status always reflects the real delivery attempt.
