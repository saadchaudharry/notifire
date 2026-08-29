// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt
//
// List view settings must live in <doctype>_list.js - a form script is only
// evaluated when a form is opened, so indicators defined there never show up
// in the list.

frappe.listview_settings["Notifire Log"] = {
	add_fields: ["status", "event", "site", "ref_name", "via_fallback"],
	hide_name_column: true,
	filters: [],
	get_indicator(doc) {
		const colors = {
			Sent: "green",
			Received: "orange",
			Failed: "red",
			Suppressed: "blue",
		};
		const status = doc.status || "Received";
		return [__(status), colors[status] || "gray", "status,=," + status];
	},
	formatters: {
		site(value, df, doc) {
			if (value) return frappe.utils.escape_html(value);
			return `<span class="text-muted">${frappe.utils.escape_html(doc.ref_name || "—")}</span>`;
		},
	},
	onload(listview) {
		listview.page.add_menu_item(__("Show only failures"), () => {
			listview.filter_area.add([["Notifire Log", "status", "=", "Failed"]]);
		});
	},
};
