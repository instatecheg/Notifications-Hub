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
	whatsapp: {
		title: "WhatsApp (Wapilot) Setup Guide",
		html: `
<div class="hub-guide">
<p>Messages are sent through <b>Wapilot</b>, a WhatsApp gateway. Customers do <b>not</b> need to link anything: the app only needs their mobile number.</p>

<h5>Step 1: Prepare your Wapilot account</h5>
<ol>
<li>Sign in to your Wapilot dashboard and connect your WhatsApp number (scan the QR code). The number must show as <b>connected / active</b>.</li>
<li>Copy your <b>API token</b> from the dashboard (API / Developer settings).</li>
<li>Note your <b>Instance ID</b> (the number used in your API URL, for example <code>4558</code>).</li>
</ol>

<h5>Step 2: Fill Notification Hub</h5>
<ol>
<li>Tick <b>Enable WhatsApp</b> and set <b>Default Country Code</b> (Egypt = <code>20</code>).</li>
<li>Paste the token in <b>Wapilot API Token</b>.</li>
<li>Set <b>Wapilot Base URL</b> according to the API you have:
<table>
<tr><th>Your API</th><th>Base URL</th><th>Extra step</th></tr>
<tr><td><b>API v2</b> (api.wapilot.net)</td><td><pre>https://api.wapilot.net/api/v2/INSTANCE_ID/send-message</pre></td><td>None. No Python package needed.</td></tr>
<tr><td><b>Classic SDK</b> (app.wapilot.io)</td><td><pre>https://app.wapilot.io</pre></td><td>Run on the server: <code>./env/bin/pip install wapilot-sdk</code> then <code>bench restart</code></td></tr>
</table></li>
<li>For API v2 leave <b>Phone Format</b> on <i>Digits only</i> unless Wapilot asks for the plus sign.</li>
<li>Click <b>Save</b>.</li>
</ol>

<h5>Step 3: Run the diagnostics</h5>
<ol>
<li>Click <b>WhatsApp Diagnostics</b>. It never sends a message; it only checks the setup.</li>
<li>For API v2, a <i>validation error (HTTP 400/422)</i> on the empty test body is the <b>expected, good</b> result. It proves the URL, instance and token are reachable.</li>
<li>Any red line tells you exactly what to fix.</li>
</ol>

<h5>Step 4: Send a test message</h5>
<ol>
<li>At the bottom, set <b>Test Channel = WhatsApp</b>.</li>
<li>Enter <b>Test Recipient</b> (for example <code>01221396684</code>; it is converted using the country code).</li>
<li>Click <b>Send Test Message</b>. A green "Sent" means it works.</li>
</ol>

<div class="note">If the test fails with "missing field" or "validation" details, open <b>Advanced (API v2 payloads)</b> and change the field names to the ones Wapilot asks for. Placeholders: <code>{phone}</code> <code>{message}</code>. Default:
<pre>{"chat_id": "{phone}", "text": "{message}"}</pre></div>

<h5>Step 5: Automatic sending</h5>
<ol>
<li>Open the <b>Notifications</b> tab, add a row, choose the Document (for example Sales Invoice), the event, and <b>Channel = WhatsApp</b> or <b>Both</b>.</li>
<li>Or use the <b>Notify Customer</b> button on a Sales Invoice for an immediate send.</li>
<li>The message comes from the notification or from a saved template (<b>Templates</b> tab). Click <b>Load Default Message</b> in a notification for the professional invoice layout.</li>
<li>Check <b>Hub Message Log</b> for the status of each message. Use <b>Retry</b> after fixing a problem.</li>
</ol>

<h5>Step 6: WhatsApp groups</h5>
<ol>
<li>Groups need <b>API v2</b>. The connected WhatsApp number must be a member of the group.</li>
<li>Click <b>WhatsApp Diagnostics</b>: it tries to list your groups. Copy the group id ending with <code>@g.us</code> (or take it from the Wapilot dashboard).</li>
<li>Add it in the <b>Groups</b> tab with Channel = WhatsApp. Test it in the <b>Test</b> tab by putting the id in Test Recipient.</li>
<li>In a notification (<b>Notifications</b> tab &gt; Edit), pick the group under <b>Send To &gt; Groups</b>.</li>
</ol>

<div class="tip"><b>PDF attachments:</b> Wapilot downloads the PDF from a URL, so your site must be reachable from the internet (set <code>host_name</code> in <code>site_config.json</code>). A site that only works on a local address such as <code>192.168.x.x</code> can send text but not PDFs.</div>
</div>`,
	},

	tg_bot: {
		title: "Telegram Bot Setup Guide",
		html: `
<div class="hub-guide">
<p><b>Bot mode</b> is the official and safest way. The customer must press <b>Start</b> on your bot once, then they receive everything automatically.</p>

<h5>Step 1: Create the bot</h5>
<ol>
<li>In Telegram open <b>@BotFather</b> and send <code>/newbot</code>.</li>
<li>Choose a name and a username ending with <code>bot</code>.</li>
<li>Copy the <b>token</b> BotFather gives you.</li>
</ol>

<h5>Step 2: Fill Notification Hub</h5>
<ol>
<li>Tick <b>Enable Telegram</b> and set <b>Mode = Bot</b>.</li>
<li>Paste the token in <b>Bot Token</b> and click <b>Save</b>.</li>
<li>Click <b>Test Connection</b>. You should see <i>Bot: @your_bot</i> and <b>Bot Username</b> is filled automatically.</li>
</ol>

<h5>Step 3: Choose how the bot receives "Start"</h5>
<table>
<tr><th>Link Method</th><th>Use when</th><th>Notes</th></tr>
<tr><td><b>Polling</b></td><td>Server is internal / no public HTTPS (default)</td><td>The scheduler must be running (it checks every minute). Verify with <code>bench doctor</code>.</td></tr>
<tr><td><b>Webhook</b></td><td>Site has a public <b>HTTPS</b> address</td><td>Click <b>Set Webhook</b> after saving.</td></tr>
</table>

<h5>Step 4: Link a customer</h5>
<ol>
<li>Open <b>Telegram Link</b> (or use the button on the Customer form). A personal link is created for the customer.</li>
<li>Send that link to the customer. They open it and press <b>Start</b>.</li>
<li>Within about a minute the status changes to <b>Linked</b> and a confirmation message appears in their chat.</li>
</ol>

<h5>Step 5: Test and automate</h5>
<ol>
<li>Set <b>Test Channel = Telegram</b>, and put a <b>chat id</b> (shown on a Linked Telegram Link) in <b>Test Recipient</b>, then click <b>Send Test Message</b>.</li>
<li>Add a notification in the <b>Notifications</b> tab with <b>Channel = Telegram</b> or <b>Both</b>, or use <b>Notify Customer</b> on a Sales Invoice.</li>
</ol>

<div class="note">A bot can never message someone who has not pressed Start. A status of <b>Not Linked</b> in Hub Message Log means exactly this.</div>
</div>`,
	},

	tg_user: {
		title: "Telegram User Account Setup Guide",
		html: `
<div class="hub-guide">
<p><b>User Account mode</b> sends from a normal Telegram account using only the customer's phone number. The customer does not need to press Start, but the number must exist on Telegram and allow contact by phone number.</p>
<div class="note">Use a <b>dedicated number</b>, not your personal account. Sending many unsolicited messages can get a user account limited or banned by Telegram. Keep the volume low and only message customers who expect it.</div>

<h5>Step 1: Get api_id and api_hash</h5>
<ol>
<li>Open <code>https://my.telegram.org</code> and log in with the account's phone number.</li>
<li>Choose <b>API development tools</b> and create an application (any name).</li>
<li>Copy <b>api_id</b> (digits only) and <b>api_hash</b>.</li>
</ol>

<h5>Step 2: Fill Notification Hub</h5>
<ol>
<li>Tick <b>Enable Telegram</b> and set <b>Mode = User Account</b>.</li>
<li>Enter <b>Api Id</b> and <b>Api Hash</b>.</li>
<li>Enter <b>Login Phone</b> (international format, for example <code>+201001234567</code>) and click <b>Save</b>.</li>
</ol>

<h5>Step 3: Log in</h5>
<ol>
<li>Click <b>Send Code</b>. A code arrives inside the Telegram app of that account (not by SMS).</li>
<li>Type it in <b>Login Code</b>. If the account has Two-Step Verification, also fill <b>Two Fa Password</b>.</li>
<li>Click <b>Verify &amp; Login</b>. <b>Account Status</b> shows the account name and <b>Session String</b> is stored.</li>
<li>Click <b>Test Connection</b> any time to confirm the session is still valid.</li>
</ol>
<div class="tip">The code is valid for 10 minutes. If you see "Click Send Code first", request a new code.</div>

<h5>Step 4: Test</h5>
<ol>
<li>Set <b>Test Channel = Telegram</b>, put a <b>mobile number</b> in <b>Test Recipient</b>, then click <b>Send Test Message</b>.</li>
<li>Use the <b>Notifications</b> tab or <b>Notify Customer</b> for real messages. Telegram Link is created automatically.</li>
</ol>
</div>`,
	},

	trouble: {
		title: "Troubleshooting",
		html: `
<div class="hub-guide">
<p>Every failed message is stored in <b>Hub Message Log</b> with a <b>Problem in</b> / <b>Cause and fix</b> text. Common cases:</p>
<table>
<tr><th>Message</th><th>Meaning and fix</th></tr>
<tr><td>HTTP 405 "Method not allowed"</td><td>The URL does not accept the request type. For WhatsApp API v2 use the <b>full</b> URL ending in <code>/send-message</code> (the app sends a POST). Browsers and GET checks always show 405 here; that is normal.</td></tr>
<tr><td>HTTP 401 / 403 (WhatsApp)</td><td>Wrong or expired Wapilot token. Generate a new one and save.</td></tr>
<tr><td>HTTP 404 (WhatsApp)</td><td>Wrong <b>Instance ID</b> in the URL, or the WhatsApp number is not connected in Wapilot.</td></tr>
<tr><td>HTTP 400 / 422 (WhatsApp)</td><td>Wapilot rejected the data. Read the technical details: they name the field. Adjust <b>Advanced (API v2 payloads)</b> or the <b>Phone Format</b>.</td></tr>
<tr><td>wapilot-sdk is not installed</td><td>Only for the classic base URL <code>https://app.wapilot.io</code>. Run <code>./env/bin/pip install wapilot-sdk</code> and <code>bench restart</code>.</td></tr>
<tr><td>Message delivered. PDF not attached</td><td>The text was sent; only the PDF failed. Usual cause: the site address is internal (WhatsApp cannot download the file) or the media endpoint differs. Fix <code>host_name</code> or <b>Media Endpoint / Media Payload</b>, or untick <b>Attach Print</b> on the rule.</td></tr>
<tr><td>Not Linked (Telegram Bot)</td><td>The customer has not pressed Start. Send them the link from <b>Telegram Link</b>.</td></tr>
<tr><td>chat not found / blocked by the user</td><td>Wrong chat id, or the customer blocked the bot. They must unblock and press Start.</td></tr>
<tr><td>Unauthorized (Telegram)</td><td>Bad bot token. Copy it again from @BotFather.</td></tr>
<tr><td>Session expired (User Account)</td><td>Log in again: <b>Send Code</b>, then <b>Verify &amp; Login</b>.</td></tr>
<tr><td>Nothing is sent automatically</td><td>Check: channel is enabled, the notification is enabled and its conditions are true, and the scheduler is running (<code>bench doctor</code>).</td></tr>
</table>
<p>After fixing a problem open the failed <b>Hub Message Log</b> entry and click <b>Retry</b>.</p>
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
	if (!dt) return frappe.msgprint(__("Select a Document first"));
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
			if (v.event === "Value Change" && !v.value_changed) return frappe.msgprint(__("Choose the field that changes"));
			if (DATE_EVENTS.includes(v.event) && !v.date_changed) return frappe.msgprint(__("Choose the Reference Date"));
			if (!v.template && !(v.message || "").trim()) return frappe.msgprint(__("Choose a Template or write a Message"));
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
		if (!dt) return area.html(`<p class="text-muted">${__("Select a Document first")}</p>`);
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
		if (!(message || "").trim()) return frappe.msgprint(__("Write the message first"));
		frappe.prompt({ fieldname: "name", fieldtype: "Data", label: __("Template Name"), reqd: 1 }, v => {
			if (template_names(frm).includes(v.name)) return frappe.msgprint(__("A template with this name already exists"));
			frm.add_child("templates", { template_name: v.name, document_type: d.get_value("document_type"), message });
			frm.refresh_field("templates");
			set_template_options();
			d.set_value("template", v.name);
			frappe.show_alert({ message: __("Template saved. It is stored when you click Save."), indicator: "green" });
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
			if (v.applies_to === "User" && !v.user) return frappe.msgprint(__("Choose a User"));
			if (v.applies_to === "Role" && !v.role) return frappe.msgprint(__("Choose a Role"));
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
		if (l.status === "Linked") return frappe.msgprint(__("{0} is already linked on Telegram.", [user]));
		if (!l.deep_link) return frappe.msgprint(__("Click Test Connection in the Telegram tab first to detect the bot username."));
		frappe.msgprint({
			title: __("Telegram Link"),
			message: __("Send this link to {0}. They open it and press Start once:", [user]) +
				`<br><br><b>${frappe.utils.escape_html(l.deep_link)}</b>`,
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
			if (other) return frappe.msgprint(__("A template with this name already exists"));
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

	btn_guide_whatsapp: () => show_guide("whatsapp"),
	btn_guide_tg_bot: () => show_guide("tg_bot"),
	btn_guide_tg_user: () => show_guide("tg_user"),
	btn_guide_trouble: () => show_guide("trouble"),
});
