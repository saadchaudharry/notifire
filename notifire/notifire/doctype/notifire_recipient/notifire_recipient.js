// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.ui.form.on("Notifire Recipient", {
	refresh(frm) {
		// Fill the hostname dropdown with every hostname listed on a Bench Group.
		frappe.call({
			method: "frappe.client.get_list",
			args: {
				doctype: "Bench Group Hostname",
				fields: ["hostname", "parent"],
				limit_page_length: 0,
				parent: "Bench Group",
			},
			callback(r) {
				const options = (r.message || []).map((row) => ({
					value: row.hostname,
					label: row.hostname,
					description: row.parent,
				}));
				frm.fields_dict.hostnames.grid.update_docfield_property(
					"hostname",
					"options",
					options
				);
			},
		});

		frm.set_intro(
			(frm.doc.hostnames || []).length
				? __("Receives events for the listed hostnames only.")
				: __("No hostnames listed, so this address receives every event, including bench and deploy events."),
			"blue"
		);
	},
	hostnames(frm) {
		frm.trigger("refresh");
	},
});
