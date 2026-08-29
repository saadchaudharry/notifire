// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.listview_settings["Notifire Recipient"] = {
	add_fields: ["enabled", "group", "scope_mode"],
	hide_name_column: true,
	get_indicator(doc) {
		if (!doc.enabled) return [__("Disabled"), "gray", "enabled,=,0"];
		if (doc.scope_mode === "Only selected sites") {
			return [__("Scoped"), "blue", "scope_mode,=,Only selected sites"];
		}
		return [__("Group default"), "green", "scope_mode,=,All sites in this group"];
	},
};
