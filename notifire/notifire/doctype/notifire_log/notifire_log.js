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
	if (!status) return "";
	const value = String(status).trim().toLowerCase();
	if (!value) return "";
	if (NOTIFIRE_GREEN.has(value)) return "\u{1F7E2}";
	if (NOTIFIRE_RED.has(value)) return "\u{1F534}";
	return "\u{1F7E1}";
}

function notifire_payload(frm) {
	try {
		return typeof frm.doc.payload === "string" && frm.doc.payload
			? JSON.parse(frm.doc.payload)
			: frm.doc.payload || {};
	} catch (e) {
		return {};
	}
}

frappe.ui.form.on("Notifire Log", {
	refresh(frm) {
		const payload = notifire_payload(frm);
		const status = payload && payload.data ? payload.data.status : null;
		const ball = notifire_ball(status);

		const bits = [];
		if (ball && status) {
			bits.push(`${ball} ${frappe.utils.escape_html(String(status))}`);
		}
		if (frm.doc.site) bits.push(frappe.utils.escape_html(frm.doc.site));
		if (frm.doc.via_fallback) bits.push(__("routed via fallback group"));
		if (bits.length) frm.dashboard.set_headline(bits.join(" &nbsp;·&nbsp; "));

		if (frm.doc.status === "Failed") {
			frm.set_intro(
				frm.doc.error || __("The notification for this event was not delivered."),
				"red"
			);
		} else if (frm.doc.status === "Suppressed") {
			frm.set_intro(
				frm.doc.error || __("Held back by the dedupe window: an identical event was just sent."),
				"blue"
			);
		} else {
			frm.set_intro("");
		}

		if (["Failed", "Suppressed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Send Now"), () => {
				frappe.confirm(
					__("Resolve recipients again and try to send this notification now?"),
					() => {
						frappe.call({
							method: "notifire.notifire.api.resend_log",
							args: { log: frm.doc.name },
							freeze: true,
							freeze_message: __("Sending…"),
							callback(r) {
								const res = r.message || {};
								frappe.show_alert({
									message: res.message || __("Done"),
									indicator: res.ok ? "green" : "red",
								});
								frm.reload_doc();
							},
						});
					}
				);
			}).addClass("btn-primary");
		}

		frm.add_custom_button(__("Copy Payload"), () => {
			frappe.utils.copy_to_clipboard(JSON.stringify(payload, null, 2));
		});

		if (frm.doc.group) {
			frm.add_custom_button(__("Group"), () => {
				frappe.set_route("Form", "Notifire Group", frm.doc.group);
			}, __("Open"));
		}
		if (frm.doc.site) {
			frm.add_custom_button(__("Site Events"), () => {
				frappe.set_route("List", "Notifire Log", { site: frm.doc.site });
			}, __("Open"));
		}
	},
});
