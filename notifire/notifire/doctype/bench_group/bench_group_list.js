// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.listview_settings["Bench Group"] = {
	add_fields: ["enabled"],
	get_indicator(doc) {
		return doc.enabled
			? [__("Enabled"), "green", "enabled,=,1"]
			: [__("Disabled"), "gray", "enabled,=,0"];
	},
};
