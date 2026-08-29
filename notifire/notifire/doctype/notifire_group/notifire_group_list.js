// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.listview_settings["Notifire Group"] = {
	add_fields: ["enabled", "fallback", "site_count"],
	hide_name_column: true,
	get_indicator(doc) {
		if (!doc.enabled) return [__("Disabled"), "gray", "enabled,=,0"];
		if (doc.fallback) return [__("Fallback"), "purple", "fallback,=,1"];
		if (!doc.site_count) return [__("No hostnames"), "orange", "site_count,=,0"];
		return [__("Active"), "green", "enabled,=,1"];
	},
};
