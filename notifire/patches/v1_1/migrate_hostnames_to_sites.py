# Copyright (c) 2026, Notifire contributors
# For license information, please see license.txt

"""Move hostnames out of the Notifire Group child table into Notifire Site.

Existing installs keep working after `bench migrate`: every row of the old
`Notifire Group Hostname` child table becomes a Notifire Site record with the
same hostname and group, recipient scopes keep pointing at the same strings
(the site docname *is* the hostname), and the obsolete child DocType is
removed.

Safe to re-run.
"""

import frappe


def execute():
    frappe.reload_doc("notifire", "doctype", "notifire_site")
    frappe.reload_doc("notifire", "doctype", "notifire_group")
    frappe.reload_doc("notifire", "doctype", "notifire_recipient")
    frappe.reload_doc("notifire", "doctype", "notifire_recipient_scope")

    if frappe.db.table_exists("Notifire Group Hostname"):
        rows = frappe.db.sql(
            """
            select `hostname`, `parent`
            from `tabNotifire Group Hostname`
            where `parenttype` = 'Notifire Group'
            order by `creation` asc
            """,
            as_dict=True,
        )
        for row in rows:
            hostname = (row.hostname or "").strip().lower()
            if not hostname or frappe.db.exists("Notifire Site", hostname):
                continue
            if not frappe.db.exists("Notifire Group", row.parent):
                continue
            doc = frappe.get_doc(
                {
                    "doctype": "Notifire Site",
                    "hostname": hostname,
                    "group": row.parent,
                    "enabled": 1,
                }
            )
            doc.flags.ignore_permissions = True
            doc.insert(ignore_if_duplicate=True)

    # Recipients that had scoped hostnames must show the explicit scope mode
    # the form now uses; everything else stays a group default.
    scoped = frappe.db.sql_list(
        """
        select distinct `parent`
        from `tabNotifire Recipient Scope`
        where `parenttype` = 'Notifire Recipient'
        """
    )
    for name in scoped:
        if frappe.db.exists("Notifire Recipient", name):
            frappe.db.set_value(
                "Notifire Recipient", name, "scope_mode", "Only selected sites",
                update_modified=False,
            )
    frappe.db.sql(
        """
        update `tabNotifire Recipient`
        set `scope_mode` = 'All sites in this group'
        where `scope_mode` is null or `scope_mode` = ''
        """
    )

    # Refresh the denormalized counter used by the group list view.
    for group in frappe.get_all("Notifire Group", pluck="name"):
        frappe.db.set_value(
            "Notifire Group",
            group,
            "site_count",
            frappe.db.count("Notifire Site", {"group": group}),
            update_modified=False,
        )

    if frappe.db.exists("DocType", "Notifire Group Hostname"):
        frappe.delete_doc("DocType", "Notifire Group Hostname", force=True, ignore_permissions=True)
