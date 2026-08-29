// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.listview_settings["Notifire Site"] = {
	add_fields: ["enabled", "group", "label"],
	hide_name_column: true,
	get_indicator(doc) {
		return doc.enabled
			? [__("Enabled"), "green", "enabled,=,1"]
			: [__("Disabled"), "gray", "enabled,=,0"];
	},
};
