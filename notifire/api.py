# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Short, stable path for the webhook receiver.

Senders are configured with

    POST /api/method/notifire.api.webhook?group=<slug>

which is the URL the Desk forms and the README hand out. The implementation
lives in ``notifire.notifire.api``; that longer path keeps working too, so
existing senders do not need to be touched.
"""

import frappe

from notifire.notifire import api as _api


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook(group=None):
    return _api.webhook(group=group)
