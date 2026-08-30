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

function notifire_ball(status) {
	const value = String(status || "").trim().toLowerCase();
	if (!value) return "";
	if (NOTIFIRE_GREEN.has(value)) return "\u{1F7E2}";
	if (NOTIFIRE_RED.has(value)) return "\u{1F534}";
	return "\u{1F7E1}";
}

frappe.ui.form.on("Notifire Log", {
	refresh(frm) {
		const ball = notifire_ball(frm.doc.event_status);
		if (!ball) return;
		const bits = [`${ball} ${frappe.utils.escape_html(frm.doc.event_status)}`];
		if (frm.doc.reference) bits.push(frappe.utils.escape_html(frm.doc.reference));
		frm.dashboard.set_headline(bits.join(" &nbsp;·&nbsp; "));
	},
});
