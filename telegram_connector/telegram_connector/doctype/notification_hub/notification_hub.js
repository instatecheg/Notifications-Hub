function run(frm, method) {
	const go = () => frm.call({ doc: frm.doc, method }).then(r => {
		if (r.message) frappe.msgprint(r.message);
		frm.reload_doc();
	});
	return frm.is_dirty() ? frm.save().then(go) : go();
}

// ---------------------------------------------------------------------------
// Setup guides (shown in a dialog when the guide buttons are clicked)
// ---------------------------------------------------------------------------
const CSS = `
<style>
.hub-guide { font-size: 13px; line-height: 1.55; }
.hub-guide h5 { margin: 16px 0 6px; font-weight: 600; }
.hub-guide ol, .hub-guide ul { padding-left: 20px; margin: 4px 0 8px; }
.hub-guide li { margin-bottom: 4px; }
.hub-guide code { background: var(--control-bg, #f3f3f3); padding: 1px 5px; border-radius: 4px; user-select: all; }
.hub-guide pre { background: var(--control-bg, #f3f3f3); padding: 8px 10px; border-radius: 6px; user-select: all; white-space: pre-wrap; }
.hub-guide table { width: 100%; border-collapse: collapse; margin: 6px 0; }
.hub-guide th, .hub-guide td { border: 1px solid var(--border-color, #ddd); padding: 5px 8px; vertical-align: top; text-align: left; }
.hub-guide th { background: var(--control-bg, #f3f3f3); }
.hub-guide .note { border-left: 3px solid var(--orange-500, #f90); padding: 4px 10px; margin: 8px 0; }
.hub-guide .tip { border-left: 3px solid var(--green-500, #2a2); padding: 4px 10px; margin: 8px 0; }
</style>`;

const GUIDES = {
	trouble: {
		title: "Troubleshooting",
		html: `
<div class="hub-guide">
<p>Every message is recorded in <b>Hub Message Log</b>. A failed message shows the <b>Issue</b>, the <b>Resolution</b>
and the technical details. The most common cases are listed below.</p>
<table>
<tr><th>Message</th><th>Meaning and resolution</th></tr>
<tr><td>HTTP 405 "Method not allowed"</td><td>The URL does not accept this type of request. For WhatsApp API v2, please use the <b>full</b> URL ending with <code>/send-message</code>.</td></tr>
<tr><td>HTTP 401 / 403 (WhatsApp)</td><td>The Wapilot token is invalid or expired. Please generate a new token and save it.</td></tr>
<tr><td>HTTP 404 / Instance not found (WhatsApp)</td><td>The <b>Instance ID</b> in the Base URL is incorrect, or the WhatsApp number is not connected in Wapilot. Please run WhatsApp Diagnostics.</td></tr>
<tr><td>HTTP 400 / 422 (WhatsApp)</td><td>Wapilot rejected the request data. The technical details name the field; please adjust <b>Advanced (API v2 payloads)</b> or the <b>Phone Format</b>.</td></tr>
<tr><td>The wapilot-sdk package is not installed</td><td>Applies to the classic Base URL <code>https://app.wapilot.io</code> only. Please run <code>./env/bin/pip install wapilot-sdk</code>, then <code>bench restart</code>.</td></tr>
<tr><td>The message was delivered, but the PDF was not attached</td><td>The text was delivered; only the PDF failed. The site address is usually not reachable from the internet, or the media endpoint differs. Please correct <code>host_name</code> or the <b>Media Endpoint / Media Payload</b>, or disable <b>Attach PDF</b> in the notification.</td></tr>
<tr><td>Not Linked (Telegram Bot)</td><td>The recipient has not opened their Telegram link and pressed Start. Please send them the link from <b>Telegram Link</b>.</td></tr>
<tr><td>Chat not found / blocked by the user</td><td>The chat id is incorrect, or the recipient has blocked the bot. They must unblock it and press Start again.</td></tr>
<tr><td>Unauthorized (Telegram)</td><td>The bot token is invalid. Please copy it again from @BotFather.</td></tr>
<tr><td>Session expired (User Account)</td><td>Please log in again: <b>Send Code</b>, then <b>Verify &amp; Login</b>.</td></tr>
<tr><td>No message is sent automatically</td><td>Please verify that the channel is enabled, the notification is enabled, its conditions are met, and the scheduler is running (<code>bench doctor</code>).</td></tr>
</table>
<p>After resolving the issue, open the failed entry in <b>Hub Message Log</b> and click <b>Retry</b>.</p>
</div>`,
	},
};

function show_guide(key) {
	const g = GUIDES[key];
	const d = new frappe.ui.Dialog({
		title: g.title,
		size: "large",
		fields: [{ fieldtype: "HTML", fieldname: "body", options: CSS + g.html }],
		primary_action_label: "Close",
		primary_action: () => d.hide(),
	});
	d.show();
}

// ---------------------------------------------------------------------------
// Notifications / User Alerts / Templates: edited in dialogs, no code needed
// ---------------------------------------------------------------------------
const EVENTS = ["New", "Save", "Submit", "Cancel", "Value Change", "Days Before", "Days After"];
const DATE_EVENTS = ["Days Before", "Days After"];
const ALERT_TYPES = [
	{ value: "Alert", description: __("Status changes and alerts made by the system") },
	{ value: "Assignment", description: __("A document was assigned to the user") },
	{ value: "Mention", description: __("Someone mentioned the user in a comment") },
	{ value: "Share", description: __("A document was shared with the user") },
	{ value: "Energy Point", description: __("Energy points") },
];
const VALUE_CHANGE_MESSAGE =
	"{{ doc.doctype }} {{ doc.name }}: {{ field_label }} changed from {{ old_value }} to {{ new_value }} by {{ changed_by }}\n{{ link }}";
const EXTRA_VALUES = [
	{ label: __("Document Name (name)"), value: "{{ doc.name }}" },
	{ label: __("Link to the document"), value: "{{ link }}" },
	{ label: __("Changed By (user full name)"), value: "{{ changed_by }}" },
	{ label: __("Value Change: field label"), value: "{{ field_label }}" },
	{ label: __("Value Change: old value"), value: "{{ old_value }}" },
	{ label: __("Value Change: new value"), value: "{{ new_value }}" },
	{ label: __("User Alert: notification text"), value: "{{ subject }}" },
];

// A titled, formal message window
const notice = (title, message, indicator = "orange") => frappe.msgprint({ title, message, indicator });

const lines = t => (t || "").split("\n").map(s => s.trim()).filter(Boolean);
const field_cache = {};

function get_fields(dt) {
	if (!dt) return Promise.resolve([]);
	if (field_cache[dt]) return Promise.resolve(field_cache[dt]);
	return frappe.call({ method: "telegram_connector.api.get_fields", args: { doctype: dt } })
		.then(r => (field_cache[dt] = r.message || []));
}

function template_names(frm, dt) {
	return (frm.doc.templates || [])
		.filter(t => t.template_name && (!dt || !t.document_type || t.document_type === dt))
		.map(t => t.template_name);
}

function template_text(frm, name) {
	const t = (frm.doc.templates || []).find(t => t.template_name === name);
	return t ? t.message : "";
}

function insert_field(dt, get, set) {
	get_fields(dt).then(fields => {
		const opts = EXTRA_VALUES.concat(
			fields.map(f => ({ label: f.label, value: `{{ doc.${f.value} }}` })));
		const d = new frappe.ui.Dialog({
			title: __("Insert Field"),
			fields: [{ fieldname: "field", fieldtype: "Autocomplete", label: __("Field"), options: opts, reqd: 1 }],
			primary_action_label: __("Insert"),
			primary_action(v) {
				const cur = get() || "";
				set(cur + (cur && !cur.endsWith("\n") && !cur.endsWith(" ") ? " " : "") + v.field);
				d.hide();
			},
		});
		d.show();
	});
}

function preview(dt, message) {
	if (!dt) return notice(__("Document Required"), __("Please select a document before previewing the message."));
	const d = new frappe.ui.Dialog({
		title: __("Preview Message"),
		fields: [{ fieldname: "docname", fieldtype: "Link", label: __("Preview with"), options: dt, reqd: 1 }],
		primary_action_label: __("Preview"),
		primary_action(v) {
			frappe.call({
				method: "telegram_connector.api.preview_message",
				args: { doctype: dt, name: v.docname, message: message || "" },
			}).then(r => {
				d.hide();
				frappe.msgprint({
					title: __("Preview"),
					message: `<pre style="white-space: pre-wrap; font-family: inherit;">${frappe.utils.escape_html(r.message || "")}</pre>`,
				});
			});
		},
	});
	d.show();
}

// Close a new row's dialog without saving: drop the empty row
function drop_if_empty(frm, table, cdn, key) {
	const row = locals[frm.fields_dict[table].grid.doctype][cdn];
	if (row && !row[key]) frm.fields_dict[table].grid.grid_rows_by_docname[cdn]?.remove();
}

const TABLE_OF = { "Hub Notification": "notifications", "Hub User Alert": "user_alerts", "Hub Message Template": "templates" };

function save_row(frm, cdt, cdn, values) {
	Object.entries(values).forEach(([k, v]) => (locals[cdt][cdn][k] = v));
	frm.dirty();
	frm.refresh_field(TABLE_OF[cdt]);
	return frm.save();
}

function edit_notification(frm, cdn) {
	const cdt = "Hub Notification";
	const row = locals[cdt][cdn];
	let filter_group = null;
	let saved = false;

	const d = new frappe.ui.Dialog({
		title: row.title || __("New Notification"),
		size: "extra-large",
		fields: [
			{ fieldtype: "Section Break", label: __("When") },
			{ fieldname: "document_type", fieldtype: "Link", options: "DocType", label: __("Document"), reqd: 1,
				onchange: () => on_doctype(true) },
			{ fieldname: "event", fieldtype: "Select", options: EVENTS.join("\n"), label: __("Event"), reqd: 1,
				onchange: () => on_event() },
			{ fieldname: "value_changed", fieldtype: "Autocomplete", label: __("Field that changes"),
				depends_on: "eval:doc.event=='Value Change'", description: __("e.g. Status") },
			{ fieldname: "date_changed", fieldtype: "Autocomplete", label: __("Reference Date"),
				depends_on: `eval:${JSON.stringify(DATE_EVENTS)}.includes(doc.event)`, description: __("Checked once a day") },
			{ fieldname: "days_in_advance", fieldtype: "Int", label: __("Days"),
				depends_on: `eval:${JSON.stringify(DATE_EVENTS)}.includes(doc.event)` },
			{ fieldtype: "Column Break" },
			{ fieldname: "channel", fieldtype: "Select", options: "WhatsApp\nTelegram\nBoth", label: __("Channel"), reqd: 1,
				description: __("For people. Groups always use their own channel.") },
			{ fieldname: "title", fieldtype: "Data", label: __("Title"), description: __("Leave empty to fill automatically") },
			{ fieldname: "enabled", fieldtype: "Check", label: __("Enabled") },

			{ fieldtype: "Section Break", label: __("Conditions"),
				description: __("Send only when all conditions are true. Leave empty to always send.") },
			{ fieldname: "filter_area", fieldtype: "HTML" },
			{ fieldtype: "Section Break", label: __("Advanced Condition (Python)"), collapsible: 1,
				collapsible_depends_on: "condition" },
			{ fieldname: "condition", fieldtype: "Code", options: "PythonExpression", label: __("Python Condition"),
				description: __("Optional, for developers. Example: doc.grand_total > 1000") },

			{ fieldtype: "Section Break", label: __("Send To") },
			{ fieldname: "send_to_contact", fieldtype: "Check", label: __("The document's customer / contact") },
			{ fieldname: "users", fieldtype: "MultiSelectPills", label: __("Users"),
				get_data: txt => frappe.db.get_link_options("User", txt, { enabled: 1, user_type: "System User" }) },
			{ fieldname: "roles", fieldtype: "MultiSelectPills", label: __("Roles"),
				get_data: txt => frappe.db.get_link_options("Role", txt) },
			{ fieldtype: "Column Break" },
			{ fieldname: "chat_groups", fieldtype: "MultiSelectPills", label: __("Groups"),
				description: __("Add groups in the Groups tab"),
				get_data: () => (frm.doc.groups || []).filter(g => g.enabled)
					.map(g => ({ value: g.group_name, description: g.channel })) },
			{ fieldname: "document_fields", fieldtype: "MultiSelectPills", label: __("People on the document"),
				description: __("A field holding a user or a mobile number, e.g. Created By (owner)"),
				get_data: () => get_fields(d.get_value("document_type")).then(fs => fs
					.filter(f => ["Data", "Link", "Dynamic Link", "Phone"].includes(f.fieldtype))
					.map(f => ({ value: f.value, description: f.label }))) },
			{ fieldname: "mobile_numbers", fieldtype: "Small Text", label: __("Mobile Numbers"), description: __("One per line") },
			{ fieldtype: "Section Break", label: __("Customer / Contact Fields"), collapsible: 1, depends_on: "send_to_contact",
				description: __("Filled automatically from the document. Change only if the mobile number is stored elsewhere.") },
			{ fieldname: "mobile_field", fieldtype: "Autocomplete", label: __("Mobile field in the document") },
			{ fieldname: "party_field", fieldtype: "Autocomplete", label: __("Customer / party field") },
			{ fieldtype: "Column Break" },
			{ fieldname: "party_doctype", fieldtype: "Link", options: "DocType", label: __("Party type"), description: __("e.g. Customer") },
			{ fieldname: "party_mobile_field", fieldtype: "Data", label: __("Mobile field in the party"), description: __("e.g. mobile_no") },
			{ fieldname: "prefer_party_mobile", fieldtype: "Check", label: __("Use the party's number first") },

			{ fieldtype: "Section Break", label: __("Message") },
			{ fieldname: "template", fieldtype: "Select", label: __("Template"),
				description: __("Pick a saved template, or leave empty and write the message"),
				onchange: () => show_template() },
			{ fieldname: "template_text", fieldtype: "HTML", depends_on: "template" },
			{ fieldname: "message", fieldtype: "Code", options: "Jinja", label: __("Message"), depends_on: "eval:!doc.template" },
			{ fieldname: "btn_insert", fieldtype: "Button", label: __("Insert Field"), depends_on: "eval:!doc.template",
				click: () => insert_field(d.get_value("document_type"), () => d.get_value("message"), v => d.set_value("message", v)) },
			{ fieldtype: "Column Break" },
			{ fieldname: "btn_preview", fieldtype: "Button", label: __("Preview"),
				click: () => preview(d.get_value("document_type"),
					d.get_value("template") ? template_text(frm, d.get_value("template")) : d.get_value("message")) },
			{ fieldtype: "Column Break" },
			{ fieldname: "btn_default", fieldtype: "Button", label: __("Load Default Message"), depends_on: "eval:!doc.template",
				click: () => load_preset(true) },
			{ fieldtype: "Column Break" },
			{ fieldname: "btn_save_template", fieldtype: "Button", label: __("Save as Template"), depends_on: "eval:!doc.template",
				click: () => save_as_template() },
			{ fieldtype: "Section Break" },
			{ fieldname: "attach_print", fieldtype: "Check", label: __("Attach PDF") },
			{ fieldtype: "Column Break" },
			{ fieldname: "print_format", fieldtype: "Link", options: "Print Format", label: __("Print Format"), depends_on: "attach_print",
				get_query: () => ({ filters: { doc_type: d.get_value("document_type") } }) },
		],
		primary_action_label: __("Save"),
		primary_action(v) {
			const dt = v.document_type;
			if (v.event === "Value Change" && !v.value_changed) return notice(__("Field Required"), __("Please select the field whose change triggers this notification."));
			if (DATE_EVENTS.includes(v.event) && !v.date_changed) return notice(__("Reference Date Required"), __("Please select the date field the days are counted from."));
			if (!v.template && !(v.message || "").trim()) return notice(__("Message Required"), __("Please select a template or enter a message."));
			const filters = filter_group ? filter_group.get_filters().map(f => f.slice(0, 4)) : [];
			saved = true;
			d.hide();
			save_row(frm, cdt, cdn, {
				enabled: v.enabled ? 1 : 0, title: v.title || "", document_type: dt, event: v.event,
				value_changed: v.value_changed || "", date_changed: v.date_changed || "", days_in_advance: v.days_in_advance || 0,
				channel: v.channel, filters: JSON.stringify(filters), condition: v.condition || "",
				send_to_contact: v.send_to_contact ? 1 : 0, users: (v.users || []).join("\n"), roles: (v.roles || []).join("\n"),
				chat_groups: (v.chat_groups || []).join("\n"), document_fields: (v.document_fields || []).join("\n"),
				mobile_numbers: lines(v.mobile_numbers).join("\n"),
				mobile_field: v.mobile_field || "", party_field: v.party_field || "", party_doctype: v.party_doctype || "",
				party_mobile_field: v.party_mobile_field || "", prefer_party_mobile: v.prefer_party_mobile ? 1 : 0,
				template: v.template || "", message: v.message || "",
				attach_print: v.attach_print ? 1 : 0, print_format: v.print_format || "",
			});
		},
	});

	function show_template() {
		const name = d.get_value("template");
		d.fields_dict.template_text.$wrapper.html(name
			? `<pre style="white-space: pre-wrap; font-family: inherit; background: var(--control-bg); padding: 8px 10px; border-radius: 6px;">${
				frappe.utils.escape_html(template_text(frm, name))}</pre>`
			: "");
	}

	function set_template_options() {
		d.set_df_property("template", "options", [""].concat(template_names(frm, d.get_value("document_type"))));
	}

	function make_filters(filters) {
		const dt = d.get_value("document_type");
		const area = d.fields_dict.filter_area.$wrapper.empty();
		filter_group = null;
		if (!dt) return area.html(`<p class="text-muted">${__("Please select a document to define conditions.")}</p>`);
		frappe.model.with_doctype(dt, () => {
			filter_group = new frappe.ui.FilterGroup({ parent: area, doctype: dt, on_change: () => {} });
			if (filters && filters.length) filter_group.add_filters_to_filter_group(filters);
		});
	}

	function load_preset(replace_message) {
		const dt = d.get_value("document_type");
		if (!dt) return;
		frappe.call({ method: "telegram_connector.api.get_preset", args: { doctype: dt } }).then(r => {
			const p = r.message || {};
			d.set_values({
				mobile_field: p.mobile_field || "", party_field: p.party_field || "", party_doctype: p.party_doctype || "",
				party_mobile_field: p.party_mobile_field || "", prefer_party_mobile: p.prefer_party_mobile ? 1 : 0,
				attach_print: p.attach_print ? 1 : 0,
			});
			// a status-change notification needs a different message than a document one
			const msg = d.get_value("event") === "Value Change" ? VALUE_CHANGE_MESSAGE : p.message;
			if (replace_message || !d.get_value("message")) d.set_value("message", msg || "");
		});
	}

	function on_doctype(changed) {
		const dt = d.get_value("document_type");
		set_template_options();
		get_fields(dt).then(fields => {
			const opts = fields.map(f => ({ value: f.value, label: f.label }));
			d.set_df_property("value_changed", "options", opts);
			d.set_df_property("date_changed", "options",
				opts.filter((_, i) => ["Date", "Datetime"].includes(fields[i].fieldtype)));
			d.set_df_property("mobile_field", "options", opts);
			d.set_df_property("party_field", "options", opts);
		});
		if (changed) {
			make_filters([]);
			load_preset(true);
		}
	}

	function on_event() {
		if (d.get_value("event") === "Value Change" && !d.get_value("template")) d.set_value("message", VALUE_CHANGE_MESSAGE);
	}

	function save_as_template() {
		const message = d.get_value("message");
		if (!(message || "").trim()) return notice(__("Message Required"), __("Please enter the message before saving it as a template."));
		frappe.prompt({ fieldname: "name", fieldtype: "Data", label: __("Template Name"), reqd: 1 }, v => {
			if (template_names(frm).includes(v.name)) {
				return notice(__("Duplicate Template Name"), __("A template named {0} already exists. Please choose a different name.", [v.name]));
			}
			frm.add_child("templates", { template_name: v.name, document_type: d.get_value("document_type"), message });
			frm.refresh_field("templates");
			set_template_options();
			d.set_value("template", v.name);
			frappe.show_alert({ message: __("The template {0} has been added. It will be stored when this notification is saved.", [v.name]), indicator: "green" });
		}, __("Save as Template"));
	}

	d.onhide = () => !saved && drop_if_empty(frm, "notifications", cdn, "document_type");
	d.show();
	const filters = JSON.parse(row.filters || "[]");
	d.set_values({
		enabled: row.enabled, title: row.title, document_type: row.document_type, event: row.event || "Submit",
		channel: row.channel || "WhatsApp", condition: row.condition, send_to_contact: row.send_to_contact,
		users: lines(row.users), roles: lines(row.roles), chat_groups: lines(row.chat_groups),
		document_fields: lines(row.document_fields), mobile_numbers: row.mobile_numbers,
		mobile_field: row.mobile_field, party_field: row.party_field, party_doctype: row.party_doctype,
		party_mobile_field: row.party_mobile_field, prefer_party_mobile: row.prefer_party_mobile,
		message: row.message, attach_print: row.attach_print, print_format: row.print_format,
		days_in_advance: row.days_in_advance,
	}).then(() => {
		on_doctype(false);
		set_template_options();
		d.set_values({ value_changed: row.value_changed, date_changed: row.date_changed, template: row.template || "" })
			.then(show_template);
		make_filters(filters);
	});
}

function edit_user_alert(frm, cdn) {
	const cdt = "Hub User Alert";
	const row = locals[cdt][cdn];
	let saved = false;
	const d = new frappe.ui.Dialog({
		title: __("User Alert"),
		size: "large",
		fields: [
			{ fieldname: "applies_to", fieldtype: "Select", options: "User\nRole", label: __("For"), reqd: 1 },
			{ fieldname: "user", fieldtype: "Link", options: "User", label: __("User"), depends_on: "eval:doc.applies_to=='User'",
				get_query: () => ({ filters: { enabled: 1, user_type: "System User" } }) },
			{ fieldname: "role", fieldtype: "Link", options: "Role", label: __("Role"), depends_on: "eval:doc.applies_to=='Role'",
				description: __("Every user with this role") },
			{ fieldname: "btn_tg_link", fieldtype: "Button", label: __("Get Telegram Link for this user"),
				depends_on: "eval:doc.applies_to=='User' && doc.user", click: () => telegram_link(d.get_value("user")) },
			{ fieldtype: "Column Break" },
			{ fieldname: "channel", fieldtype: "Select", options: "WhatsApp\nTelegram\nBoth", label: __("Send on"), reqd: 1,
				description: __("WhatsApp uses the user's Mobile No. Telegram (Bot) needs the user to open their Telegram link once.") },
			{ fieldname: "enabled", fieldtype: "Check", label: __("Enabled") },
			{ fieldtype: "Section Break", label: __("Which notifications") },
			{ fieldname: "types", fieldtype: "MultiSelectPills", label: __("Types"), description: __("Empty = all types"),
				get_data: () => ALERT_TYPES },
			{ fieldtype: "Column Break" },
			{ fieldname: "document_types", fieldtype: "MultiSelectPills", label: __("Documents"),
				description: __("Empty = all documents, e.g. Delivery Trip"),
				get_data: txt => frappe.db.get_link_options("DocType", txt, { istable: 0 }) },
			{ fieldtype: "Section Break", label: __("Message") },
			{ fieldname: "template", fieldtype: "Select", label: __("Template"), options: [""].concat(template_names(frm)),
				description: __("Empty = the notification text as it appears in the bell, with a link to the document") },
		],
		primary_action_label: __("Save"),
		primary_action(v) {
			if (v.applies_to === "User" && !v.user) return notice(__("User Required"), __("Please select a user."));
			if (v.applies_to === "Role" && !v.role) return notice(__("Role Required"), __("Please select a role."));
			saved = true;
			d.hide();
			save_row(frm, cdt, cdn, {
				applies_to: v.applies_to, user: v.applies_to === "User" ? v.user : "", role: v.applies_to === "Role" ? v.role : "",
				channel: v.channel, enabled: v.enabled ? 1 : 0, types: (v.types || []).join("\n"),
				document_types: (v.document_types || []).join("\n"), template: v.template || "",
			});
		},
	});
	d.onhide = () => !saved && drop_if_empty(frm, "user_alerts", cdn, row.applies_to === "Role" ? "role" : "user");
	d.show();
	d.set_values({
		applies_to: row.applies_to || "User", user: row.user, role: row.role, channel: row.channel || "WhatsApp",
		enabled: row.enabled, types: lines(row.types), document_types: lines(row.document_types), template: row.template || "",
	});
}

function telegram_link(user) {
	frappe.call({ method: "telegram_connector.api.get_user_telegram_link", args: { user } }).then(r => {
		const l = r.message || {};
		if (l.status === "Linked") return notice(__("Already Linked"), __("The user {0} is already linked on Telegram.", [user]), "green");
		if (!l.deep_link) return notice(__("Bot Username Missing"), __("The bot username is not known yet. Please click Test Connection in the Telegram tab first."));
		frappe.msgprint({
			title: __("Telegram Link"),
			message: __("Please send this link to {0}. Once they open it and press Start, they will receive their alerts on Telegram. The link has been copied to the clipboard.", [user]) +
				`<br><br><b>${frappe.utils.escape_html(l.deep_link)}</b>`,
			indicator: "blue",
		});
		frappe.utils.copy_to_clipboard(l.deep_link);
	});
}

function edit_template(frm, cdn) {
	const cdt = "Hub Message Template";
	const row = locals[cdt][cdn];
	let saved = false;
	const d = new frappe.ui.Dialog({
		title: row.template_name || __("New Template"),
		size: "large",
		fields: [
			{ fieldname: "template_name", fieldtype: "Data", label: __("Template Name"), reqd: 1 },
			{ fieldtype: "Column Break" },
			{ fieldname: "document_type", fieldtype: "Link", options: "DocType", label: __("For Document"),
				description: __("Optional. Needed for Insert Field and Preview.") },
			{ fieldtype: "Section Break" },
			{ fieldname: "message", fieldtype: "Code", options: "Jinja", label: __("Message"), reqd: 1 },
			{ fieldname: "btn_insert", fieldtype: "Button", label: __("Insert Field"),
				click: () => insert_field(d.get_value("document_type"), () => d.get_value("message"), v => d.set_value("message", v)) },
			{ fieldtype: "Column Break" },
			{ fieldname: "btn_preview", fieldtype: "Button", label: __("Preview"),
				click: () => preview(d.get_value("document_type"), d.get_value("message")) },
		],
		primary_action_label: __("Save"),
		primary_action(v) {
			const other = (frm.doc.templates || []).find(t => t.name !== cdn && t.template_name === v.template_name);
			if (other) return notice(__("Duplicate Template Name"), __("A template named {0} already exists. Please choose a different name.", [v.template_name]));
			// keep notifications and alerts pointing at a renamed template
			if (row.template_name && row.template_name !== v.template_name) {
				[...(frm.doc.notifications || []), ...(frm.doc.user_alerts || [])]
					.filter(r => r.template === row.template_name).forEach(r => (r.template = v.template_name));
			}
			saved = true;
			d.hide();
			save_row(frm, cdt, cdn, { template_name: v.template_name, document_type: v.document_type || "", message: v.message });
		},
	});
	d.onhide = () => !saved && drop_if_empty(frm, "templates", cdn, "template_name");
	d.show();
	d.set_values({ template_name: row.template_name, document_type: row.document_type, message: row.message });
}

// Open the dialog instead of the plain row form
function use_dialog(table, open) {
	return {
		[`${table}_add`]: (frm, cdt, cdn) => open(frm, cdn),
		btn_edit: (frm, cdt, cdn) => open(frm, cdn),
		form_render(frm, cdt, cdn) {
			frm.fields_dict[table].grid.grid_rows_by_docname[cdn]?.toggle_view(false);
			open(frm, cdn);
		},
	};
}

frappe.ui.form.on("Hub Notification", use_dialog("notifications", edit_notification));
frappe.ui.form.on("Hub User Alert", use_dialog("user_alerts", edit_user_alert));
frappe.ui.form.on("Hub Message Template", use_dialog("templates", edit_template));

frappe.ui.form.on("Notification Hub", {
	btn_test_connection: f => run(f, "test_connection"),
	btn_set_webhook: f => run(f, "set_webhook"),
	btn_send_code: f => run(f, "send_login_code"),
	btn_verify: f => run(f, "verify_login_code"),
	btn_send_test: f => run(f, "send_test_message"),
	btn_wa_check: f => run(f, "diagnose_whatsapp"),

	btn_guide_trouble: () => show_guide("trouble"),
});
