// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt
//
// List settings must live in <doctype>_list.js. In <doctype>.js they are only
// evaluated when a form opens, so the list never picks them up.

frappe.listview_settings["Notifire Log"] = {
	add_fields: ["status", "site", "reference"],
	get_indicator(doc) {
		const colors = { Sent: "green", Received: "orange", Failed: "red", Suppressed: "blue" };
		const status = doc.status || "Received";
		return [__(status), colors[status] || "gray", "status,=," + status];
	},
	formatters: {
		site(value, df, doc) {
			return frappe.utils.escape_html(value || doc.reference || "—");
		},
	},
};
