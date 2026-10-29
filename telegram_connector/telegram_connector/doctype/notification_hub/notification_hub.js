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
<li>Open <b>Hub Notification Rule</b>, choose the DocType (for example Sales Invoice), the event, and <b>Channel = WhatsApp</b> or <b>Both</b>.</li>
<li>Or use the <b>Notify Customer</b> button on a Sales Invoice for an immediate send.</li>
<li>The message text comes from the rule. For the professional invoice layout open the rule and click <b>Template &gt; Load Default Template</b>, then Save. Existing rules keep their old text until you do this.</li>
<li>Check <b>Hub Message Log</b> for the status of each message. Use <b>Retry</b> after fixing a problem.</li>
</ol>

<h5>Step 6: WhatsApp groups</h5>
<ol>
<li>Groups need <b>API v2</b>. The connected WhatsApp number must be a member of the group.</li>
<li>Click <b>WhatsApp Diagnostics</b>: it tries to list your groups. Copy the group id ending with <code>@g.us</code> (or take it from the Wapilot dashboard).</li>
<li>Create a <b>Hub Chat Group</b> with Channel = WhatsApp and that id. Test it in the <b>Test</b> tab by putting the id in Test Recipient.</li>
<li>In a <b>Hub Notification Rule</b>, pick the group under <b>Recipients &gt; Groups</b>.</li>
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
<li>Create a <b>Hub Notification Rule</b> with <b>Channel = Telegram</b> or <b>Both</b>, or use <b>Notify Customer</b> on a Sales Invoice.</li>
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
<li>Use <b>Hub Notification Rule</b> or <b>Notify Customer</b> for real messages. Telegram Link is created automatically.</li>
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
<tr><td>Nothing is sent automatically</td><td>Check: channel is enabled, the Hub Notification Rule is enabled and its condition is true, and the scheduler is running (<code>bench doctor</code>).</td></tr>
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
