// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt
//
// The one rule that trips people up here: a site with its own selected
// recipients ignores the group defaults. So the form spells out, live, which
// hostnames this address will actually receive mail for.

const NOTIFIRE_ALL_SITES = "All sites in this group";
const NOTIFIRE_SELECTED_SITES = "Only selected sites";

frappe.ui.form.on("Notifire Recipient", {
	setup(frm) {
		notifire_recipient_styles();
		// Only hostnames belonging to this recipient's group can be picked.
		frm.set_query("hostname", "applies_to", () => ({
			filters: { group: frm.doc.group || "" },
		}));
	},

	refresh(frm) {
		notifire_recipient_styles();
		frm.set_intro("");
		if (!frm.doc.enabled && !frm.is_new()) {
			frm.set_intro(__("This recipient is disabled and receives nothing."), "orange");
		}
		if (frm.doc.group && !frm.is_new()) {
			frm.add_custom_button(__("Open Group"), () => {
				frappe.set_route("Form", "Notifire Group", frm.doc.group);
			});
		}
		notifire_render_coverage(frm);
	},

	group(frm) {
		// Scopes belong to one group; keeping them across a group change
		// would silently produce a recipient that never fires.
		if ((frm.doc.applies_to || []).length) {
			frm.clear_table("applies_to");
			frm.refresh_field("applies_to");
			frappe.show_alert({
				message: __("Selected sites cleared: they belonged to the previous group."),
				indicator: "orange",
			});
		}
		notifire_render_coverage(frm);
	},

	scope_mode(frm) {
		if (frm.doc.scope_mode === NOTIFIRE_ALL_SITES && (frm.doc.applies_to || []).length) {
			frm.clear_table("applies_to");
			frm.refresh_field("applies_to");
		}
		notifire_render_coverage(frm);
	},

	enabled(frm) {
		notifire_render_coverage(frm);
	},

	applies_to(frm) {
		notifire_render_coverage(frm);
	},
});

frappe.ui.form.on("Notifire Recipient Scope", {
	applies_to_add(frm) {
		notifire_render_coverage(frm);
	},
	applies_to_remove(frm) {
		notifire_render_coverage(frm);
	},
	hostname(frm) {
		notifire_render_coverage(frm);
	},
});

function notifire_render_coverage(frm) {
	const field = frm.get_field("coverage_html");
	if (!field) return;

	if (!frm.doc.group) {
		field.$wrapper.html(
			`<div class="notifire-empty">${__("Pick a notification group to see what this address will receive.")}</div>`
		);
		return;
	}

	frappe.call({
		method: "notifire.notifire.api.group_overview",
		args: { group: frm.doc.group },
		callback(r) {
			if (!r.message) return;
			notifire_draw_coverage(frm, field, r.message);
		},
	});
}

function notifire_draw_coverage(frm, field, data) {
	const esc = frappe.utils.escape_html;
	const sites = data.sites || [];
	const selected = (frm.doc.applies_to || []).map((row) => row.hostname).filter(Boolean);

	// What other enabled recipients have claimed, ignoring this document.
	const claimed = {};
	(data.recipients || [])
		.filter((rec) => rec.name !== frm.doc.name && rec.enabled)
		.forEach((rec) => {
			rec.applies_to.forEach((host) => {
				claimed[host] = claimed[host] || [];
				claimed[host].push(rec.email);
			});
		});

	if (!sites.length) {
		field.$wrapper.html(`
			<div class="notifire-warning">
				${__("Group {0} has no hostnames mapped yet.", [esc(data.group.title || data.group.name)])}
				${__("It only receives events that fall through to the fallback group.")}
			</div>
			<button class="btn btn-xs btn-default" data-action="open-group">${__("Map hostnames")}</button>
		`);
		field.$wrapper.find('[data-action="open-group"]').on("click", () => {
			frappe.set_route("Form", "Notifire Group", frm.doc.group);
		});
		return;
	}

	let covered = [];
	let excluded = [];
	let summary = "";

	if (frm.doc.scope_mode === NOTIFIRE_SELECTED_SITES) {
		covered = sites.filter((s) => selected.includes(s.hostname));
		summary = covered.length
			? __("Receives events for the selected hostnames only, replacing the group defaults for them.")
			: __("No sites selected yet, so this address receives nothing.");
	} else {
		covered = sites.filter((s) => !(claimed[s.hostname] || []).length);
		excluded = sites.filter((s) => (claimed[s.hostname] || []).length);
		summary = __("Default recipient: receives every hostname that has no recipients of its own.");
	}

	const chip = (site) => {
		const off = site.enabled ? "" : ` <span class="notifire-chip-meta">${__("disabled")}</span>`;
		return `<span class="notifire-chip"><span class="notifire-chip-host">${esc(site.hostname)}</span>${off}</span>`;
	};

	const coveredHtml = covered.length
		? `<div class="notifire-chips">${covered.map(chip).join("")}</div>`
		: `<div class="notifire-empty">${__("Nothing.")}</div>`;

	const excludedHtml = excluded.length
		? `<div class="notifire-sub">${__("Skipped, because these hostnames have their own recipients:")}</div>
			<div class="notifire-chips">${excluded
				.map(
					(s) =>
						`<span class="notifire-chip notifire-chip-off"><span class="notifire-chip-host">${esc(
							s.hostname
						)}</span><span class="notifire-chip-meta">${esc(
							(claimed[s.hostname] || []).join(", ")
						)}</span></span>`
				)
				.join("")}</div>`
		: "";

	const disabled = frm.doc.enabled
		? ""
		: `<div class="notifire-warning">${__("This recipient is disabled, so nothing is sent to it right now.")}</div>`;

	field.$wrapper.html(`
		${disabled}
		<div class="notifire-sub">${summary}</div>
		${coveredHtml}
		${excludedHtml}
		<div class="notifire-toolbar" style="margin-top:12px">
			${
				frm.doc.scope_mode === NOTIFIRE_SELECTED_SITES
					? `<button class="btn btn-xs btn-default" data-action="select-all">${__(
							"Select every hostname"
					  )}</button>`
					: ""
			}
			<button class="btn btn-xs btn-default" data-action="open-group">${__("Open group")}</button>
		</div>
	`);

	field.$wrapper.find('[data-action="open-group"]').on("click", () => {
		frappe.set_route("Form", "Notifire Group", frm.doc.group);
	});
	field.$wrapper.find('[data-action="select-all"]').on("click", () => {
		frm.clear_table("applies_to");
		sites.forEach((site) => {
			frm.add_child("applies_to", { hostname: site.hostname });
		});
		frm.refresh_field("applies_to");
		notifire_render_coverage(frm);
	});
}

function notifire_recipient_styles() {
	if (document.getElementById("notifire-recipient-styles")) return;
	const style = document.createElement("style");
	style.id = "notifire-recipient-styles";
	style.textContent = `
		.notifire-chips { display: flex; flex-wrap: wrap; gap: 8px; margin: 6px 0 12px; }
		.notifire-chip { display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--border-color); border-radius: 999px; padding: 4px 10px; }
		.notifire-chip-off { opacity: 0.6; }
		.notifire-chip-host { font-weight: 500; }
		.notifire-chip-meta { color: var(--text-muted); font-size: var(--text-xs); border-left: 1px solid var(--border-color); padding-left: 8px; }
		.notifire-sub { color: var(--text-muted); font-size: var(--text-sm); margin-bottom: 4px; }
		.notifire-empty { color: var(--text-muted); padding: 6px 0; }
		.notifire-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
		.notifire-warning { border-left: 3px solid var(--orange-500, #f0a500); padding: 6px 10px; margin-bottom: 8px; background: var(--control-bg); border-radius: var(--border-radius); }
	`;
	document.head.appendChild(style);
}
