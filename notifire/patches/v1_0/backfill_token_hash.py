# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Fill in Bench Group.token_hash for groups created before token lookup.

The endpoint used to carry ?group=<name>, which Frappe Cloud rejects, so the
token identifies the group now and is looked up by fingerprint. Existing
groups keep their token; they just need the hash column populated.
"""

import frappe
from frappe.utils.password import get_decrypted_password

from notifire.notifire.doctype.bench_group.bench_group import fingerprint


def execute():
    frappe.reload_doc("notifire", "doctype", "bench_group")

    for name in frappe.get_all("Bench Group", pluck="name"):
        token = get_decrypted_password("Bench Group", name, "token", raise_exception=False)
        if token:
            frappe.db.set_value(
                "Bench Group", name, "token_hash", fingerprint(token), update_modified=False
            )

    # The URL no longer takes a query parameter.
    base = frappe.utils.get_url().rstrip("/")
    frappe.db.sql(
        "update `tabBench Group` set webhook_url = %s", ("{}/api/method/notifire.api.webhook".format(base),)
    )
