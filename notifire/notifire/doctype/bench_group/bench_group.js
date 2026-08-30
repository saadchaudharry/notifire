// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.ui.form.on("Bench Group", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.set_intro(
				__("Name this the same as your Frappe Cloud bench group, e.g. bench-0019. The URL and token are generated when you save."),
				"blue"
			);
			return;
		}
		frm.set_intro("");

		frm.add_custom_button(__("Copy URL"), () => {
			frappe.utils.copy_to_clipboard(frm.doc.webhook_url);
		});
		frm.add_custom_button(__("Copy Token"), () => {
			frappe.call({
				method: "notifire.api.get_token",
				args: { group: frm.doc.name },
				callback(r) {
					frappe.utils.copy_to_clipboard((r.message && r.message.token) || "");
				},
			});
		});
		frm.add_custom_button(__("Regenerate Token"), () => {
			frappe.confirm(
				__("The old token stops working immediately. Update it in Frappe Cloud afterwards."),
				() => {
					frappe.call({
						method: "notifire.api.regenerate_token",
						args: { group: frm.doc.name },
						freeze: true,
						callback() {
							frm.reload_doc();
							frappe.show_alert({ message: __("New token generated"), indicator: "green" });
						},
					});
				}
			);
		});
	},
});
