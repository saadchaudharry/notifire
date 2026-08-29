// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt

frappe.ui.form.on("Notifire Site", {
	refresh(frm) {
		if (frm.is_new()) {
			frm.set_intro(
				__("Add the hostname exactly as Frappe Cloud sends it, e.g. test465.frappe.cloud."),
				"blue"
			);
			frm.get_field("help_html").$wrapper.empty();
			return;
		}

		frm.set_intro("");
		if (!frm.doc.enabled) {
			frm.set_intro(
				__("This hostname is disabled: its events fall through to the fallback group."),
				"orange"
			);
		}

		frm.add_custom_button(__("Open Group"), () => {
			frappe.set_route("Form", "Notifire Group", frm.doc.group);
		});
		frm.add_custom_button(__("Recent Events"), () => {
			frappe.set_route("List", "Notifire Log", { site: frm.doc.hostname });
		});

		render_site_coverage(frm);
	},
});

function render_site_coverage(frm) {
	const field = frm.get_field("help_html");
	if (!field) return;
	field.$wrapper.html(`<div class="text-muted">${__("Loading…")}</div>`);

	frappe.call({
		method: "notifire.notifire.api.group_overview",
		args: { group: frm.doc.group },
		callback(r) {
			const data = r.message;
			if (!data) {
				field.$wrapper.empty();
				return;
			}
			const site = (data.sites || []).find((s) => s.hostname === frm.doc.hostname);
			if (!site) {
				field.$wrapper.empty();
				return;
			}

			const esc = frappe.utils.escape_html;
			let body = "";
			if (!site.recipients.length) {
				body = `<div class="text-danger">${__(
					"Nobody is set up to receive events for this site."
				)}</div>`;
			} else if (site.source === "scoped") {
				body = `<div>${__("Scoped recipients (they replace the group defaults for this site):")}</div>
					<div style="margin-top:6px">${site.recipients
						.map((e) => `<code>${esc(e)}</code>`)
						.join(" ")}</div>`;
			} else {
				body = `<div>${__("Group default recipients:")}</div>
					<div style="margin-top:6px">${site.recipients
						.map((e) => `<code>${esc(e)}</code>`)
						.join(" ")}</div>`;
			}

			field.$wrapper.html(`
				<div class="notifire-panel" style="border:1px solid var(--border-color);border-radius:var(--border-radius-md);padding:12px 14px">
					${body}
					<div class="text-muted" style="margin-top:10px;font-size:var(--text-sm)">
						${__("Edit this list from the recipient rows of group {0}.", [esc(data.group.title || data.group.name)])}
					</div>
				</div>
			`);
		},
	});
}
