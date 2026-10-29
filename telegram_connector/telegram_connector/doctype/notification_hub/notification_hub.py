import re

import frappe
from frappe.model.document import Document
from frappe.utils.password import set_encrypted_password

from telegram_connector import sender

DT = "Notification Hub"


def _tmp_key():
    return f"telegram_login:{frappe.session.user}"


def _cache():
    # frappe.cache is a function in v15 and an object in v16
    c = frappe.cache
    return c if hasattr(c, "set_value") else c()


def _run(coro):
    """Run Telethon code and turn any error into a readable message instead of a Server Error."""
    try:
        return sender.run_async(coro)
    except frappe.ValidationError:
        raise
    except Exception as e:
        frappe.throw(f"{type(e).__name__}: {e}")


def _set(field, value):
    frappe.db.set_single_value(DT, field, value)


# Password fields we write directly to __Auth (not through the form).
SECRET_FIELDS = ("session_string", "webhook_secret")


def _set_secret(field, value):
    """Store a secret encrypted AND leave a dummy '*****' in the Single table.

    Frappe deletes a Password value from __Auth when the form is saved with an empty
    value. Because these fields are never typed into the form, the form would always
    send them empty and wipe the secret on the next Save. The dummy value prevents that.
    """
    set_encrypted_password(DT, DT, value, field)
    _set(field, "*" * 10)


STD_FIELDS = {"name", "owner", "modified_by", "docstatus", "creation", "modified", "idx"}


def _check_field(meta, fieldname, where):
    if not fieldname:
        frappe.throw(f"{where}: choose a field")
    if fieldname not in STD_FIELDS and not meta.has_field(fieldname):
        frappe.throw(f"{where}: {meta.name} has no field '{fieldname}'")


def _check_jinja(text, where):
    from jinja2 import Environment, TemplateSyntaxError

    try:
        Environment().parse(text or "")
    except TemplateSyntaxError as e:
        frappe.throw(f"{where}: error in the message: {e}")


def _send_to_summary(r):
    parts = []
    if r.send_to_contact:
        parts.append("Customer")
    for label, field in (("User", "users"), ("Role", "roles"), ("Number", "mobile_numbers"),
                         ("Field", "document_fields"), ("Group", "chat_groups")):
        items = sender._lines(r.get(field))
        if items:
            parts.append(f"{label}: " + ", ".join(items[:2]) + (f" +{len(items) - 2}" if len(items) > 2 else ""))
    return "; ".join(parts)[:140]


class NotificationHub(Document):
    def validate(self):
        # Never let a form save wipe a stored secret (see _set_secret)
        for f in SECRET_FIELDS:
            if not self.get(f) and self.get_password(f, raise_exception=False):
                self.set(f, "*" * 10)
        self.validate_groups()
        self.validate_templates()
        self.validate_notifications()
        self.validate_user_alerts()

    def validate_groups(self):
        names = set()
        for g in self.groups:
            g.chat_id = (g.chat_id or "").strip()
            where = f"Groups row {g.idx} ({g.group_name})"
            if g.group_name in names:
                frappe.throw(f"{where}: the group name is used twice")
            names.add(g.group_name)
            if g.channel == "WhatsApp" and not g.chat_id.endswith("@g.us"):
                frappe.throw(f"{where}: a WhatsApp group id ends with @g.us, e.g. 120363012345678901@g.us. "
                             "WhatsApp Diagnostics lists your groups.")
            if g.channel == "Telegram" and not re.fullmatch(r"-\d+|@\w{4,}", g.chat_id):
                frappe.throw(f"{where}: a Telegram group chat id is a negative number, e.g. -1001234567890")

    def validate_templates(self):
        names = set()
        for t in self.templates:
            if t.template_name in names:
                frappe.throw(f"Templates row {t.idx}: the name {t.template_name} is used twice")
            names.add(t.template_name)
            _check_jinja(t.message, f"Templates row {t.idx} ({t.template_name})")

    def validate_notifications(self):
        templates = {t.template_name for t in self.templates}
        groups = {g.group_name for g in self.groups}
        titles = set()
        for r in self.notifications:
            if not r.title:
                r.title = f"{r.document_type} - {r.event}" + (f" ({r.value_changed})" if r.event == "Value Change" else "")
            base, n = r.title, 1
            while r.title in titles:
                n += 1
                r.title = f"{base} ({n})"
            titles.add(r.title)
            where = f"Notification {r.idx} ({r.title})"
            if self.flags.skip_rule_checks:
                r.send_to = _send_to_summary(r)
                continue
            meta = frappe.get_meta(r.document_type)
            if r.event == "Value Change":
                _check_field(meta, r.value_changed, f"{where}: Value Changed")
            if r.event in ("Days Before", "Days After"):
                _check_field(meta, r.date_changed, f"{where}: Reference Date")
                df = meta.get_field(r.date_changed)
                if df and df.fieldtype not in ("Date", "Datetime"):
                    frappe.throw(f"{where}: Reference Date '{r.date_changed}' is not a date field")
            for f in sender.rule_filters(r):
                _check_field(meta, f[1], f"{where}: Conditions")
            for f in sender._lines(r.document_fields):
                _check_field(meta, f, f"{where}: Document Fields")
            missing = set(sender._lines(r.chat_groups)) - groups
            if missing:
                frappe.throw(f"{where}: unknown group(s) {', '.join(missing)}. Add them in the Groups tab")
            if r.template and r.template not in templates:
                frappe.throw(f"{where}: template '{r.template}' does not exist in the Templates tab")
            if not r.template and not (r.message or "").strip():
                frappe.throw(f"{where}: choose a Template or write a Message")
            _check_jinja(r.message, where)
            r.send_to = _send_to_summary(r)
            if not r.send_to:
                frappe.throw(f"{where}: choose at least one recipient")

    def validate_user_alerts(self):
        templates = {t.template_name for t in self.templates}
        for r in self.user_alerts:
            if r.template and r.template not in templates:
                frappe.throw(f"User Alerts row {r.idx}: template '{r.template}' does not exist in the Templates tab")
            types = sender._lines(r.types)
            doctypes = sender._lines(r.document_types)
            r.summary = (", ".join(types) or "All notifications") + " / " + (", ".join(doctypes) or "all documents")

    @frappe.whitelist()
    def test_connection(self):
        frappe.only_for("System Manager")
        if self.mode == "Bot":
            me = sender.bot_call("getMe")
            _set("bot_username", me.get("username"))
            if self.link_method == "Polling":
                sender.bot_call("deleteWebhook")
            return f"✅ Bot: @{me.get('username')}"
        a, h = sender._creds(self)
        who = _run(sender._user_me(a, h, sender._session(self)))
        _set("account_status", who)
        return f"✅ Account: {who}"

    @frappe.whitelist()
    def set_webhook(self):
        frappe.only_for("System Manager")
        url = frappe.utils.get_url() + "/api/method/telegram_connector.api.webhook"
        if not url.startswith("https://"):
            frappe.throw("Webhook requires a public HTTPS URL. Use Polling if the server is internal.")
        secret = self.get_password("webhook_secret", raise_exception=False)
        if not secret:
            secret = frappe.generate_hash(length=32)
            _set_secret("webhook_secret", secret)
        sender.bot_call("setWebhook", {"url": url, "secret_token": secret, "allowed_updates": '["message"]'})
        return "✅ Webhook has been set"

    @frappe.whitelist()
    def send_login_code(self):
        frappe.only_for("System Manager")
        phone = sender.normalize_phone(self.login_phone, self.default_country_code)
        if not phone:
            frappe.throw("Enter the account phone number (Login Phone)")
        a, h = sender._creds(self)
        sess, code_hash = _run(sender._send_code(a, h, phone))
        # Keep the temporary state in the cache, not in the Single doctype,
        # because saving the form rewrites the Single values and loses the hash
        _cache().set_value(_tmp_key(), {"sess": sess, "hash": code_hash}, expires_in_sec=600)
        return "The code was sent to your Telegram app. Enter it in Login Code, then click Verify & Login."

    @frappe.whitelist()
    def verify_login_code(self):
        frappe.only_for("System Manager")
        phone = sender.normalize_phone(self.login_phone, self.default_country_code)
        state = _cache().get_value(_tmp_key()) or {}
        tmp, code_hash = state.get("sess"), state.get("hash")
        if not (tmp and code_hash):
            frappe.throw("Click Send Code first (the code stays valid for 10 minutes)")
        if not (self.login_code or "").strip():
            frappe.throw("Enter the code in the Login Code field")
        a, h = sender._creds(self)
        pw = self.get_password("two_fa_password", raise_exception=False)
        sess, who = _run(sender._verify(a, h, tmp, phone, self.login_code.strip(), code_hash, pw))
        _set_secret("session_string", sess)
        _cache().delete_value(_tmp_key())
        _set("account_status", who)
        _set("login_code", "")
        return f"✅ Logged in: {who}"

    @frappe.whitelist()
    def send_test_message(self):
        frappe.only_for("System Manager")
        r = (self.test_recipient or "").strip()
        if not r:
            frappe.throw("Enter a Test Recipient (WhatsApp: mobile number. Telegram: chat id in Bot mode, or a mobile number in User Account mode)")
        text = self.test_text or "Test message from ERPNext"
        if (self.test_channel or "Telegram") == "WhatsApp":
            if not self.whatsapp_enabled:
                frappe.throw("Enable WhatsApp first")
            to = r if sender.is_wa_group(r) else sender.normalize_phone(r, self.default_country_code)
            sender.wa_send(to, text)
            return "✅ Sent"
        if self.mode == "Bot":
            sender.send_text(r, None, text)
        else:
            sender.send_text(None, sender.normalize_phone(r, self.default_country_code), text)
        return "✅ Sent"

    @frappe.whitelist()
    def diagnose_whatsapp(self):
        """Step-by-step WhatsApp check that shows exactly which part is wrong. Never sends a message."""
        frappe.only_for("System Manager")
        import re

        import requests

        rows = []
        ok = lambda t: rows.append(f"✅ {t}")
        warn = lambda t: rows.append(f"⚠️ {t}")
        bad = lambda t: rows.append(f"❌ {t}")
        esc = frappe.utils.escape_html
        out = lambda: "<br>".join(rows)

        token = self.get_password("wapilot_token", raise_exception=False)
        ok("Wapilot API Token is set") if token else bad("Wapilot API Token is empty. Paste it from your Wapilot dashboard")
        base = sender.wa_base(self) or sender.WA_CLASSIC_BASE
        m = re.match(r"(https?://[^/]+)(/.*)?$", base)
        if not m:
            bad(f"Base URL must start with https:// ({esc(base)})")
            return out()
        origin, path = m.group(1), m.group(2) or ""

        def list_instances():
            # Best effort: ask Wapilot for the account's instances so the right ID can be copied from here
            if not token:
                return
            u = f"{origin}/api/v2/instances"
            try:
                rr = requests.get(u, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=15)
            except Exception as e:
                warn(f"Could not list instances ({type(e).__name__}). Copy the instance ID from the Wapilot dashboard")
                return
            if rr.status_code == 200:
                ok(f"Instances in your Wapilot account (copy the ID of the connected one into the Base URL): <code>{esc(rr.text[:800])}</code>")
            else:
                warn(f"Could not list instances (HTTP {rr.status_code}). Copy the instance ID from the Wapilot dashboard. Reply: {esc(rr.text[:200])}")

        # ---------------- API v2 ----------------
        if sender.wa_is_v2(self):
            ok("Mode: Wapilot API v2 (no SDK package needed)")
            try:
                url, media = sender.wa_v2_urls(self)
            except frappe.ValidationError as e:
                bad(esc(str(e)).replace("\n", "<br>"))
                list_instances()
                return out()
            ok(f"Send URL: {esc(url)}")
            ok(f"Media URL (PDF): {esc(media)}")
            try:
                sample = sender._wa_render(self.wapilot_payload, sender.WA_DEFAULT_TEXT,
                                           phone=sender._wa_fmt_phone("201000000000", self), message="Hello")
                ok(f"Payload that will be sent: <code>{esc(frappe.as_json(sample, indent=None))}</code>")
            except frappe.ValidationError as e:
                bad(esc(str(e)))
                return out()
            if not token:
                return out()
            try:
                # Empty body on purpose: the API validates it and answers with the fields it needs. Nothing is sent.
                r = requests.post(url, json={}, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=15)
            except Exception as e:
                bad(f"The server could not reach {esc(origin)}: {type(e).__name__}. Check the internet/DNS and the URL")
                return out()
            ok(f"Server reached {esc(origin)} (HTTP {r.status_code}) for POST {esc(url)} with an empty test body")
            reply = esc(r.text[:300])
            if r.status_code in (401, 403):
                bad(f"The token was rejected. Generate a new one in the Wapilot dashboard. Reply: {reply}")
            elif r.status_code == 404:
                bad(f"Not found: check the INSTANCE ID in the URL and that the number is connected in Wapilot. Reply: {reply}")
                list_instances()
            elif r.status_code == 405:
                bad(f"This URL does not accept POST. Use the full send URL ending with /send-message. Reply: {reply}")
            elif r.status_code in (400, 422):
                ok("The endpoint exists and answered the empty test body with a validation error. This is the expected result")
                warn(f"API reply (it shows which fields it expects): {reply}")
                ok("Next: use Send Test Message at the bottom. If it fails, the error will show the exact field to change in Advanced (API v2 payloads)")
            elif r.status_code == 200:
                warn(f"The API accepted an empty body. Reply: {reply}")
            elif r.status_code >= 500:
                bad(f"Wapilot server problem. Try again later. Reply: {reply}")
            else:
                warn(f"HTTP {r.status_code}: {reply}")

            # ---- PDF / media endpoint probe (empty body, nothing is sent) ----
            root = url[: -len("/send-message")] if url.endswith("/send-message") else url
            hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            found = False
            rows.append("<b>PDF / media endpoint probe</b> (empty test body, nothing is sent):")
            for name in ("send-media", "send-document", "send-file", "send-image", "send-attachment", "send-document-message", "send-media-message"):
                u = f"{root}/{name}"
                try:
                    rr = requests.post(u, json={}, headers=hdr, timeout=10)
                except Exception as e:
                    warn(f"{name}: {type(e).__name__}")
                    continue
                if rr.status_code == 404:
                    rows.append(f"&nbsp;&nbsp;– {esc(name)}: not found")
                else:
                    found = True
                    ok(f"{esc(name)}: <b>exists</b> (HTTP {rr.status_code}). Reply: {esc(rr.text[:300])}")
            if found:
                ok("Put the working name in Media Endpoint (Advanced) and set Media Payload to the fields shown in its reply")
            else:
                warn("No common media endpoint was found. Check the Wapilot API documentation (send file / document) for the exact URL")

            # ---- WhatsApp groups (read only) ----
            rows.append("<b>WhatsApp groups</b> (copy a group id ending with @g.us into the Groups tab):")
            listed = False
            for name in ("groups", "get-groups", "chats"):
                try:
                    rr = requests.get(f"{root}/{name}", headers=hdr, timeout=15)
                except Exception as e:
                    warn(f"{name}: {type(e).__name__}")
                    continue
                if rr.status_code == 200 and "@g.us" in rr.text:
                    ids = sorted(set(re.findall(r"[\w-]+@g\.us", rr.text)))
                    ok(f"Found {len(ids)} group(s) via {esc(name)}:<br>" + "<br>".join(f"<code>{esc(i)}</code>" for i in ids[:50]))
                    rows.append(f"Full reply: <code>{esc(rr.text[:1500])}</code>")
                    listed = True
                    break
                rows.append(f"&nbsp;&nbsp;– {esc(name)}: HTTP {rr.status_code}")
            if not listed:
                warn("Could not list groups automatically. Get the group id (…@g.us) from the Wapilot dashboard, "
                     "then test it here with Test Channel = WhatsApp and the group id as Test Recipient")
            return out()

        # ---------------- Classic SDK ----------------
        try:
            import wapilot  # noqa: F401
            ok("wapilot-sdk package is installed")
        except ImportError:
            bad("wapilot-sdk package is not installed. Run: ./env/bin/pip install wapilot-sdk then bench restart")
        if path:
            bad(f"Base URL has a path after the domain ({esc(base)}). Classic mode needs the domain only, e.g. https://app.wapilot.io. For API v2 use https://api.wapilot.net/api/v2/&lt;INSTANCE_ID&gt;/send-message")
            return out()
        ok(f"Mode: classic SDK. Base URL format is fine ({esc(base)})")
        if not token:
            return out()
        url = f"{origin}/api/contacts"
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        except Exception as e:
            bad(f"The server could not reach {esc(origin)}: {type(e).__name__}. Check the internet and the URL")
            return out()
        ok(f"Server reached {esc(origin)} (HTTP {r.status_code}) for GET {esc(url)}")
        head = r.text[:500].lower()
        if r.status_code == 200:
            ok("The token is accepted and the API answers")
        elif r.status_code in (401, 403):
            bad("The token was rejected. Generate a new one in the Wapilot dashboard")
        elif r.status_code == 404 and ("<html" in head or "<!doctype" in head):
            bad("This URL reaches a website page, not the API. The Base URL is wrong")
        else:
            bad(f"Unexpected answer HTTP {r.status_code}: {esc(r.text[:200])}")
        return out()
