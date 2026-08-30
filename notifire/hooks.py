app_name = "notifire"
app_title = "Notifire"
app_publisher = "Notifire contributors"
app_description = "Frappe Cloud webhook receiver: email site, bench and deploy events to the right people."
app_email = "support@example.com"
app_license = "mit"

required_apps = []

after_install = "notifire.install.after_install"

# The only endpoint:
#   POST /api/method/notifire.api.webhook?group=<bench group name>
#   Header: X-Webhook-Secret: <group token or global secret>
#
# No scheduler, no doc_events, no background workers: mail is sent inside the
# request (now=True) so the log status is always a real delivery result.

# Logs hold up to 100 KB of payload each; keep a month and let Frappe's daily
# log clearing drop the rest.
default_log_clearing_doctypes = {"Notifire Log": 30}
