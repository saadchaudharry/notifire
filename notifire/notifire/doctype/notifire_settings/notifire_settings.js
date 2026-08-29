// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.ui.form.on("Notifire Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Send Test Email"), () => notifire_test_email(frm));
		frm.add_custom_button(__("Show Global Secret"), () => notifire_global_secret(frm, false));
		frm.add_custom_button(__("Rotate Global Secret"), () => notifire_global_secret(frm, true));

		if (!frm.doc.enabled) {
			frm.set_intro(
				__("Email notifications are off. Webhooks are still accepted and logged as Received."),
				"orange"
			);
		} else {
			frm.set_intro("");
		}

		notifire_render_health(frm);
	},
});

function notifire_render_health(frm) {
	const field = frm.get_field("health_html");
	if (!field) return;
	field.$wrapper.html(`<div class="text-muted">${__("Loading…")}</div>`);

	frappe.call({
		method: "notifire.notifire.api.settings_overview",
		callback(r) {
			const data = r.message;
			if (!data) return;
			const esc = frappe.utils.escape_html;

			const tile = (label, value, tone) => `
				<div style="flex:1 1 120px;min-width:120px;border:1px solid var(--border-color);border-radius:var(--border-radius-md);padding:10px 12px">
					<div style="font-size:var(--text-xl);font-weight:600;color:${tone || "var(--text-color)"}">${esc(
						String(value)
					)}</div>
					<div class="text-muted" style="font-size:var(--text-sm)">${label}</div>
				</div>`;

			const problems = (data.problems || [])
				.map(
					(p) =>
						`<div style="border-left:3px solid var(--orange-500,#f0a500);padding:6px 10px;margin-top:8px;background:var(--control-bg);border-radius:var(--border-radius)">${esc(
							p
						)}</div>`
				)
				.join("");

			field.$wrapper.html(`
				<div style="display:flex;flex-wrap:wrap;gap:10px">
					${tile(__("Groups"), data.groups)}
					${tile(__("Hostnames"), data.sites)}
					${tile(__("Recipients"), data.recipients)}
					${tile(__("Sent (24h)"), data.sent_24h, "var(--green-600, #22c55e)")}
					${tile(__("Failed (24h)"), data.failed_24h, data.failed_24h ? "var(--red-500, #e24c4c)" : null)}
				</div>
				${problems}
			`);
		},
	});
}

function notifire_test_email(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Send Test Email"),
		fields: [
			{
				fieldtype: "Data",
				fieldname: "recipient",
				label: __("Send to"),
				options: "Email",
				reqd: 1,
				default: frappe.session.user_email,
			},
			{
				fieldtype: "HTML",
				fieldname: "note",
				options: `<div class="text-muted">${__(
					"Sends a sample notification through the same code path as a real webhook, so it also proves your outgoing email account works."
				)}</div>`,
			},
		],
		primary_action_label: __("Send"),
		primary_action(values) {
			frappe.call({
				method: "notifire.notifire.api.send_test_email",
				args: { recipient: values.recipient },
				freeze: true,
				freeze_message: __("Sending…"),
				callback(r) {
					dialog.hide();
					const res = r.message || {};
					if (res.ok) {
						frappe.msgprint({
							title: __("Sent"),
							message: __("A test notification was sent to {0}.", [values.recipient]),
							indicator: "green",
						});
					} else {
						frappe.msgprint({
							title: __("Not sent"),
							message: frappe.utils.escape_html(res.error || __("Unknown error")),
							indicator: "red",
						});
					}
				},
			});
		},
	});
	dialog.show();
}

function notifire_global_secret(frm, rotate) {
	const run = () => {
		frappe.call({
			method: "notifire.notifire.api.global_secret",
			args: { rotate: rotate ? 1 : 0 },
			freeze: true,
			callback(r) {
				const secret = (r.message && r.message.secret) || "";
				if (rotate) frm.reload_doc();
				frappe.msgprint({
					title: rotate ? __("New global secret") : __("Global fallback secret"),
					message: `<pre style="white-space:pre-wrap;word-break:break-all">${frappe.utils.escape_html(
						secret
					)}</pre>`,
					indicator: rotate ? "orange" : "blue",
				});
			},
		});
	};

	if (!rotate) return run();
	frappe.confirm(
		__(
			"Rotate the global fallback secret? Any sender still using the old master key will start getting 401s."
		),
		run
	);
}
