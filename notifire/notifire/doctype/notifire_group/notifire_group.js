// Copyright (c) 2026, Notifire contributors
// For license information, please see license.txt
//
// The group form is the control panel for one endpoint: where to send the
// webhook, which hostnames route here, and who gets the mail. Everything is
// rendered from a single `group_overview` call so the three panels can never
// disagree with each other.

frappe.ui.form.on("Notifire Group", {
	setup(frm) {
		notifire_inject_styles();
	},

	title(frm) {
		// Auto-fill the slug while the group is new, so nobody has to guess
		// what a valid slug looks like.
		if (frm.is_new() && !frm.doc.__slug_touched) {
			frm.set_value("slug", notifire_slugify(frm.doc.title || ""));
		}
	},

	slug(frm) {
		if (frm.doc.slug) {
			frm.doc.__slug_touched = true;
		}
	},

	refresh(frm) {
		notifire_inject_styles();

		if (frm.is_new()) {
			frm.set_intro(
				__(
					"Save this group first. A webhook secret is generated automatically, then you can map hostnames and add recipients right here."
				),
				"blue"
			);
			["webhook_html", "sites_html", "recipients_html"].forEach((f) => {
				const field = frm.get_field(f);
				if (field) {
					field.$wrapper.html(
						`<div class="notifire-empty">${__("Available after the first save.")}</div>`
					);
				}
			});
			return;
		}

		frm.set_intro("");
		if (!frm.doc.enabled) {
			frm.set_intro(
				__("This group is disabled. Its webhook endpoint answers as if it did not exist."),
				"red"
			);
		}

		frm.add_custom_button(__("Copy Webhook URL"), () => notifire_copy_url(frm), __("Webhook"));
		frm.add_custom_button(__("Show Secret"), () => notifire_show_secret(frm), __("Webhook"));
		frm.add_custom_button(__("Rotate Secret"), () => notifire_rotate_secret(frm), __("Webhook"));
		frm.add_custom_button(__("Recent Events"), () => {
			frappe.set_route("List", "Notifire Log", { group: frm.doc.name });
		});

		notifire_render_panels(frm);
	},
});

// ---------------------------------------------------------------------------
// Data + rendering
// ---------------------------------------------------------------------------

function notifire_render_panels(frm) {
	["webhook_html", "sites_html", "recipients_html"].forEach((f) => {
		const field = frm.get_field(f);
		if (field) field.$wrapper.html(`<div class="notifire-empty">${__("Loading…")}</div>`);
	});

	frappe.call({
		method: "notifire.notifire.api.group_overview",
		args: { group: frm.doc.name },
		callback(r) {
			if (!r.message) return;
			frm.__notifire = r.message;
			notifire_render_webhook(frm, r.message);
			notifire_render_sites(frm, r.message);
			notifire_render_recipients(frm, r.message);
		},
	});
}

function notifire_render_webhook(frm, data) {
	const field = frm.get_field("webhook_html");
	if (!field) return;
	const esc = frappe.utils.escape_html;

	field.$wrapper.html(`
		<div class="notifire-card">
			<div class="notifire-kv">
				<div class="notifire-kv-label">${__("Method & URL")}</div>
				<div class="notifire-kv-value">
					<span class="notifire-pill">POST</span>
					<code class="notifire-code">${esc(data.webhook_url)}</code>
					<button class="btn btn-xs btn-default" data-action="copy-url">${__("Copy")}</button>
				</div>
			</div>
			<div class="notifire-kv">
				<div class="notifire-kv-label">${__("Header")}</div>
				<div class="notifire-kv-value">
					<code class="notifire-code">X-Webhook-Secret: <span data-secret>••••••••••••••••</span></code>
					<button class="btn btn-xs btn-default" data-action="show-secret">${__("Show")}</button>
				</div>
			</div>
			<div class="notifire-kv">
				<div class="notifire-kv-label">${__("Test it")}</div>
				<div class="notifire-kv-value">
					<button class="btn btn-xs btn-default" data-action="copy-curl">${__("Copy test curl")}</button>
					<span class="notifire-hint">${__(
						"Sends a Webhook Validate event: it is logged, but no email goes out."
					)}</span>
				</div>
			</div>
		</div>
	`);

	field.$wrapper.find('[data-action="copy-url"]').on("click", () => notifire_copy_url(frm));
	field.$wrapper.find('[data-action="show-secret"]').on("click", function () {
		const $btn = $(this);
		notifire_fetch_secret(frm).then((secret) => {
			field.$wrapper.find("[data-secret]").text(secret);
			$btn.text(__("Copy")).off("click").on("click", () => {
				frappe.utils.copy_to_clipboard(secret);
			});
		});
	});
	field.$wrapper.find('[data-action="copy-curl"]').on("click", () => {
		notifire_fetch_secret(frm).then((secret) => {
			const curl =
				`curl -X POST "${data.webhook_url}" \\\n` +
				`     -H "X-Webhook-Secret: ${secret}" \\\n` +
				`     -H "Content-Type: application/json" \\\n` +
				`     -d '{"event": "Webhook Validate"}'`;
			frappe.utils.copy_to_clipboard(curl);
		});
	});
}

function notifire_render_sites(frm, data) {
	const field = frm.get_field("sites_html");
	if (!field) return;
	const esc = frappe.utils.escape_html;

	const chips = (data.sites || [])
		.map((site) => {
			const cover = site.recipients.length
				? `<span class="notifire-chip-meta">${site.recipients.length} ${
						site.source === "scoped" ? __("scoped") : __("default")
				  }</span>`
				: `<span class="notifire-chip-meta notifire-danger">${__("no recipients")}</span>`;
			const label = site.label
				? `<span class="notifire-chip-label">${esc(site.label)}</span>`
				: "";
			const off = site.enabled ? "" : " notifire-chip-off";
			return `
				<span class="notifire-chip${off}" data-host="${esc(site.hostname)}">
					<span class="notifire-chip-host" data-action="open-site">${esc(site.hostname)}</span>
					${label}${cover}
					<a href="#" class="notifire-chip-x" data-action="remove-site" title="${__("Remove")}">&times;</a>
				</span>`;
		})
		.join("");

	const empty = `<div class="notifire-empty">${__(
		"No hostnames mapped yet. Until you add one, events from these sites go to the fallback group."
	)}</div>`;

	field.$wrapper.html(`
		<div class="notifire-toolbar">
			<button class="btn btn-xs btn-primary" data-action="add-hosts">${__("Add Hostnames")}</button>
			<button class="btn btn-xs btn-default" data-action="open-sites">${__("Open Hostname List")}</button>
			<span class="notifire-hint">${__("{0} mapped", [(data.sites || []).length])}</span>
		</div>
		<div class="notifire-chips">${chips || empty}</div>
	`);

	field.$wrapper.find('[data-action="add-hosts"]').on("click", () => notifire_add_hosts_dialog(frm));
	field.$wrapper.find('[data-action="open-sites"]').on("click", () => {
		frappe.set_route("List", "Notifire Site", { group: frm.doc.name });
	});
	field.$wrapper.find('[data-action="open-site"]').on("click", function () {
		frappe.set_route("Form", "Notifire Site", $(this).closest(".notifire-chip").data("host"));
	});
	field.$wrapper.find('[data-action="remove-site"]').on("click", function (e) {
		e.preventDefault();
		const hostname = $(this).closest(".notifire-chip").data("host");
		frappe.confirm(
			__("Stop routing {0} to this group? Its events will fall through to the fallback group.", [
				`<b>${frappe.utils.escape_html(hostname)}</b>`,
			]),
			() => {
				frappe.call({
					method: "notifire.notifire.api.remove_hostname",
					args: { group: frm.doc.name, hostname: hostname },
					freeze: true,
					callback() {
						frappe.show_alert({ message: __("Removed {0}", [hostname]), indicator: "green" });
						frm.reload_doc();
					},
				});
			}
		);
	});
}

function notifire_render_recipients(frm, data) {
	const field = frm.get_field("recipients_html");
	if (!field) return;
	const esc = frappe.utils.escape_html;

	const rows = (data.recipients || [])
		.map((rec) => {
			const scope = rec.applies_to.length
				? rec.applies_to.map((h) => `<code>${esc(h)}</code>`).join(" ")
				: `<span class="text-muted">${__("All sites (default)")}</span>`;
			const state = rec.enabled
				? ""
				: `<span class="notifire-chip-meta">${__("disabled")}</span>`;
			return `
				<tr data-name="${esc(rec.name)}">
					<td><a href="#" data-action="open-recipient">${esc(rec.email)}</a> ${state}</td>
					<td>${scope}</td>
				</tr>`;
		})
		.join("");

	const table = rows
		? `<table class="notifire-table">
				<thead><tr><th>${__("Email")}</th><th>${__("Applies to")}</th></tr></thead>
				<tbody>${rows}</tbody>
			</table>`
		: `<div class="notifire-empty">${__(
				"No recipients yet. Events for this group will be logged as Failed until you add one."
		  )}</div>`;

	const warnings = (data.warnings || [])
		.map((w) => `<div class="notifire-warning">${esc(w)}</div>`)
		.join("");

	field.$wrapper.html(`
		<div class="notifire-toolbar">
			<button class="btn btn-xs btn-primary" data-action="add-recipient">${__("Add Recipient")}</button>
			<button class="btn btn-xs btn-default" data-action="open-recipients">${__("Open Recipient List")}</button>
		</div>
		${warnings}
		${table}
	`);

	field.$wrapper.find('[data-action="add-recipient"]').on("click", () => {
		frappe.new_doc("Notifire Recipient", { group: frm.doc.name });
	});
	field.$wrapper.find('[data-action="open-recipients"]').on("click", () => {
		frappe.set_route("List", "Notifire Recipient", { group: frm.doc.name });
	});
	field.$wrapper.find('[data-action="open-recipient"]').on("click", function (e) {
		e.preventDefault();
		frappe.set_route("Form", "Notifire Recipient", $(this).closest("tr").data("name"));
	});
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function notifire_add_hosts_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Add Hostnames"),
		size: "large",
		fields: [
			{
				fieldtype: "Small Text",
				fieldname: "hostnames",
				label: __("Hostnames"),
				reqd: 1,
				description: __(
					"One per line. Commas, spaces and pasted https:// URLs are cleaned up automatically."
				),
			},
			{
				fieldtype: "Data",
				fieldname: "label",
				label: __("Label for all of these"),
				description: __("Optional, e.g. \"Production - Acme\"."),
			},
			{
				fieldtype: "Check",
				fieldname: "move_existing",
				label: __("Move hostnames that currently belong to another group"),
			},
		],
		primary_action_label: __("Add"),
		primary_action(values) {
			frappe.call({
				method: "notifire.notifire.api.add_hostnames",
				args: {
					group: frm.doc.name,
					hostnames: values.hostnames,
					label: values.label || "",
					move_existing: values.move_existing ? 1 : 0,
				},
				freeze: true,
				freeze_message: __("Mapping hostnames…"),
				callback(r) {
					dialog.hide();
					notifire_show_add_result(r.message || {});
					frm.reload_doc();
				},
			});
		},
	});
	dialog.show();
}

function notifire_show_add_result(result) {
	const esc = frappe.utils.escape_html;
	const parts = [];
	if ((result.added || []).length) {
		parts.push(
			`<p><b>${__("Added")}</b><br>${result.added.map((h) => `<code>${esc(h)}</code>`).join(" ")}</p>`
		);
	}
	if ((result.moved || []).length) {
		parts.push(
			`<p><b>${__("Moved to this group")}</b><br>${result.moved
				.map((h) => `<code>${esc(h)}</code>`)
				.join(" ")}</p>`
		);
	}
	if ((result.skipped || []).length) {
		const rows = result.skipped
			.map((s) => `<tr><td><code>${esc(s.hostname)}</code></td><td>${esc(s.reason)}</td></tr>`)
			.join("");
		parts.push(
			`<p><b>${__("Skipped")}</b></p><table class="table table-bordered"><tbody>${rows}</tbody></table>`
		);
	}
	if (!parts.length) parts.push(`<p>${__("Nothing to add.")}</p>`);

	const clean = (result.skipped || []).length === 0;
	if (clean && (result.added || []).length && !(result.moved || []).length) {
		frappe.show_alert({
			message: __("{0} hostname(s) mapped", [result.added.length]),
			indicator: "green",
		});
		return;
	}
	frappe.msgprint({
		title: __("Hostname map updated"),
		message: parts.join(""),
		indicator: clean ? "green" : "orange",
	});
}

function notifire_fetch_secret(frm) {
	if (frm.__notifire_secret) {
		return Promise.resolve(frm.__notifire_secret);
	}
	return frappe
		.call({ method: "notifire.notifire.api.get_group_secret", args: { group: frm.doc.name } })
		.then((r) => {
			frm.__notifire_secret = (r.message && r.message.secret) || "";
			return frm.__notifire_secret;
		});
}

function notifire_copy_url(frm) {
	const url =
		(frm.__notifire && frm.__notifire.webhook_url) ||
		`${window.location.origin}/api/method/notifire.api.webhook?group=${encodeURIComponent(
			frm.doc.slug
		)}`;
	frappe.utils.copy_to_clipboard(url);
}

function notifire_show_secret(frm) {
	notifire_fetch_secret(frm).then((secret) => {
		frappe.msgprint({
			title: __("Webhook secret"),
			message: `<p>${__("Send this in the X-Webhook-Secret header.")}</p>
				<pre class="notifire-code-block">${frappe.utils.escape_html(secret)}</pre>`,
			indicator: "blue",
		});
	});
}

function notifire_rotate_secret(frm) {
	frappe.confirm(
		__(
			"Rotate the webhook secret? The old one stops working immediately, so update every sender that uses it."
		),
		() => {
			frappe.call({
				method: "notifire.notifire.api.rotate_group_secret",
				args: { group: frm.doc.name },
				freeze: true,
				callback(r) {
					frm.__notifire_secret = (r.message && r.message.secret) || "";
					frm.reload_doc();
					frappe.msgprint({
						title: __("New webhook secret"),
						message: `<p>${__("Copy this into every sender for this group.")}</p>
							<pre class="notifire-code-block">${frappe.utils.escape_html(frm.__notifire_secret)}</pre>`,
						indicator: "orange",
					});
				},
			});
		}
	);
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

function notifire_slugify(value) {
	return String(value)
		.toLowerCase()
		.replace(/[^a-z0-9]+/g, "-")
		.replace(/^-+|-+$/g, "");
}

function notifire_inject_styles() {
	if (document.getElementById("notifire-desk-styles")) return;
	const style = document.createElement("style");
	style.id = "notifire-desk-styles";
	style.textContent = `
		.notifire-card { border: 1px solid var(--border-color); border-radius: var(--border-radius-md); padding: 12px 14px; background: var(--fg-color); }
		.notifire-kv { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 6px 0; }
		.notifire-kv + .notifire-kv { border-top: 1px solid var(--border-color); }
		.notifire-kv-label { min-width: 110px; color: var(--text-muted); font-size: var(--text-sm); }
		.notifire-kv-value { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
		.notifire-code { background: var(--bg-light-gray, var(--control-bg)); padding: 3px 8px; border-radius: var(--border-radius); word-break: break-all; }
		.notifire-code-block { white-space: pre-wrap; word-break: break-all; }
		.notifire-pill { background: var(--bg-blue, #e8f0fe); color: var(--text-on-blue, #1a56db); border-radius: var(--border-radius); padding: 2px 8px; font-size: var(--text-xs); font-weight: 600; }
		.notifire-toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
		.notifire-hint { color: var(--text-muted); font-size: var(--text-sm); }
		.notifire-chips { display: flex; flex-wrap: wrap; gap: 8px; }
		.notifire-chip { display: inline-flex; align-items: center; gap: 8px; border: 1px solid var(--border-color); border-radius: 999px; padding: 4px 10px; background: var(--fg-color); }
		.notifire-chip-off { opacity: 0.55; }
		.notifire-chip-host { cursor: pointer; font-weight: 500; }
		.notifire-chip-host:hover { text-decoration: underline; }
		.notifire-chip-label { color: var(--text-muted); font-size: var(--text-sm); }
		.notifire-chip-meta { color: var(--text-muted); font-size: var(--text-xs); border-left: 1px solid var(--border-color); padding-left: 8px; }
		.notifire-chip-x { color: var(--text-muted); text-decoration: none; font-size: 15px; line-height: 1; }
		.notifire-chip-x:hover { color: var(--red-500, #e24c4c); text-decoration: none; }
		.notifire-danger { color: var(--red-500, #e24c4c); }
		.notifire-empty { color: var(--text-muted); padding: 10px 0; }
		.notifire-warning { border-left: 3px solid var(--orange-500, #f0a500); padding: 6px 10px; margin-bottom: 8px; background: var(--bg-light-gray, var(--control-bg)); border-radius: var(--border-radius); }
		.notifire-table { width: 100%; }
		.notifire-table th { text-align: left; font-weight: 500; color: var(--text-muted); font-size: var(--text-sm); padding: 6px 8px; border-bottom: 1px solid var(--border-color); }
		.notifire-table td { padding: 6px 8px; border-bottom: 1px solid var(--border-color); vertical-align: top; }
	`;
	document.head.appendChild(style);
}
