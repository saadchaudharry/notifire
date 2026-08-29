// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

// Traffic-light balls in the log list view (green up / yellow busy / red down).
frappe.listview_settings["Notifire Log"] = {
	add_fields: ["status", "event", "site", "ref_name"],
	get_indicator(doc) {
		const colors = {
			Sent: "green",
			Received: "orange",
			Failed: "red",
			Suppressed: "blue",
		};
		return [__(doc.status || "Received"), colors[doc.status] || "gray", "status,=," + (doc.status || "Received")];
	},
};

const GREEN = new Set(["active", "live", "up", "running", "online", "healthy", "ok", "success", "succeeded", "complete", "completed", "ready", "deployed", "published", "passed", "available"]);
const RED = new Set(["broken", "down", "failed", "failure", "error", "crashed", "dead", "offline", "suspended", "deleted", "cancelled", "canceled", "unreachable"]);

function notifire_ball(status) {
	if (!status) return "";
	const value = String(status).trim().toLowerCase();
	if (!value) return "";
	if (GREEN.has(value)) return "\u{1F7E2}";
	if (RED.has(value)) return "\u{1F534}";
	return "\u{1F7E1}";
}

frappe.ui.form.on("Notifire Log", {
	refresh(frm) {
		try {
			const payload = typeof frm.doc.payload === "string" && frm.doc.payload
				? JSON.parse(frm.doc.payload)
				: frm.doc.payload || {};
			const status = payload && payload.data ? payload.data.status : null;
			const ball = notifire_ball(status);
			if (ball && status) {
				frm.dashboard.set_headline(
					__("Site status: {0} {1}", [ball, frappe.utils.escape_html(String(status))])
				);
			}
		} catch (e) {
			// payload is not valid JSON - nothing to show
		}
	},
});
