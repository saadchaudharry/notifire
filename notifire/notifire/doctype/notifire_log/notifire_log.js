// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

const NOTIFIRE_GREEN = new Set([
	"active", "live", "up", "running", "online", "healthy", "ok", "success",
	"succeeded", "complete", "completed", "ready", "deployed", "published",
	"passed", "available",
]);
const NOTIFIRE_RED = new Set([
	"broken", "down", "failed", "failure", "error", "crashed", "dead",
	"offline", "suspended", "deleted", "cancelled", "canceled", "unreachable",
]);

frappe.ui.form.on("Notifire Log", {
	refresh(frm) {
		let status = null;
		try {
			const payload =
				typeof frm.doc.payload === "string" ? JSON.parse(frm.doc.payload) : frm.doc.payload || {};
			status = payload.data ? payload.data.status : null;
		} catch (e) {
			// payload is not valid JSON, nothing to show
		}
		if (!status) return;

		const value = String(status).trim().toLowerCase();
		const ball = NOTIFIRE_GREEN.has(value)
			? "\u{1F7E2}"
			: NOTIFIRE_RED.has(value)
			? "\u{1F534}"
			: "\u{1F7E1}";
		frm.dashboard.set_headline(`${ball} ${frappe.utils.escape_html(String(status))}`);
	},
});
