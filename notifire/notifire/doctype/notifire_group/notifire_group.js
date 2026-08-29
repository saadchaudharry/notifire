// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.ui.form.on("Notifire Group", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.set_intro(
				__("A webhook secret is generated automatically when you save. Add every Frappe Cloud site hostname that should route to this group.")
			);
			return;
		}

		const webhook_url = `${window.location.origin}/api/method/notifire.api.webhook?group=${encodeURIComponent(frm.doc.slug)}`;
		frm.dashboard.set_headline(webhook_url);

		frm.add_custom_button(__("Copy Webhook URL"), () => {
			frappe.utils.copy_to_clipboard(webhook_url);
		});

		frm.add_custom_button(__("Rotate Secret"), () => {
			frappe.confirm(
				__("Rotate the webhook secret? The old secret stops working immediately."),
				() => {
					frappe.call({
						method: "notifire.notifire.api.rotate_group_secret",
						args: { group: frm.doc.name },
						callback(r) {
							frm.reload_doc();
							const secret = (r.message && r.message.secret) || "";
							frappe.msgprint({
								title: __("New webhook secret"),
								message: `<code>${frappe.utils.escape_html(secret)}</code>`,
								indicator: "blue",
							});
						},
					});
				}
			);
		});
	},
});
