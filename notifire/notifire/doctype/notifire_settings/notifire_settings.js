// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.ui.form.on("Notifire Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Show Global Secret"), () => show_secret(frm, 0));
		frm.add_custom_button(__("Rotate Global Secret"), () => {
			frappe.confirm(
				__("Any sender still using the old global secret will start getting 401s."),
				() => show_secret(frm, 1)
			);
		});
	},
});

function show_secret(frm, rotate) {
	frappe.call({
		method: "notifire.api.global_secret",
		args: { rotate: rotate },
		freeze: true,
		callback(r) {
			if (rotate) frm.reload_doc();
			frappe.msgprint({
				title: rotate ? __("New global secret") : __("Global secret"),
				message: `<pre style="white-space:pre-wrap;word-break:break-all">${frappe.utils.escape_html(
					(r.message && r.message.secret) || ""
				)}</pre>`,
				indicator: rotate ? "orange" : "blue",
			});
		},
	});
}
