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
        frappe.throw(f"Telegram returned an error: {type(e).__name__}: {esc(e)}", title="Telegram Error")


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
        frappe.throw(f"{where}: please select a field.", title="Invalid Configuration")
    if fieldname not in STD_FIELDS and not meta.has_field(fieldname):
        frappe.throw(f"{where}: the field '{fieldname}' does not exist in {meta.name}.", title="Invalid Configuration")


def _check_jinja(text, where):
    from jinja2 import Environment, TemplateSyntaxError

    try:
        Environment().parse(text or "")
    except TemplateSyntaxError as e:
        frappe.throw(f"{where}: the message contains a template error: {esc(e)}", title="Invalid Configuration")


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


def esc(value):
    return frappe.utils.escape_html(str(value or ""))


def result(title, message, indicator="green"):
    """A titled message shown by the form (see run() in notification_hub.js)."""
    return {"title": title, "message": message, "indicator": indicator}


PILL = {"Passed": "green", "Warning": "orange", "Failed": "red", "Info": "blue"}


def _diagnostics_report(rows):
    body = "".join(
        f'<tr><td style="width:90px"><span class="indicator-pill {PILL[status]}">{status}</span></td><td>{text}</td></tr>'
        for status, text in rows)
    statuses = {s for s, _ in rows}
    indicator = "red" if "Failed" in statuses else "orange" if "Warning" in statuses else "green"
    summary = {"red": "One or more checks failed. Please review the items marked Failed.",
               "orange": "The configuration works, with warnings that may need attention.",
               "green": "All checks passed."}[indicator]
    return result("WhatsApp Diagnostics",
                  f"<p>{summary} No message was sent during this check.</p>"
                  f'<table class="table table-bordered" style="font-size:13px">{body}</table>', indicator)


class NotificationHub(Document):
    def validate(self):
        # Never let a form save wipe a stored secret (see _set_secret)
        for f in SECRET_FIELDS:
            if not self.get(f) and self.get_password(f, raise_exception=False):
                self.set(f, "*" * 10)
        self.validate_groups()
        self.validate_templates()
        self.sync_group_notifications()
        self.validate_notifications()
        self.validate_user_alerts()
        self.set_used_in()

    def validate_groups(self):
        names = set()
        for g in self.groups:
            g.chat_id = (g.chat_id or "").strip()
            where = f"Groups, row {g.idx} ({esc(g.group_name)})"
            if g.group_name in names:
                frappe.throw(f"{where}: this group name is already in use. Please choose a unique name.", title="Invalid Configuration")
            names.add(g.group_name)
            if g.channel == "WhatsApp" and not g.chat_id.endswith("@g.us"):
                frappe.throw(f"{where}: a WhatsApp group id must end with @g.us, e.g. 120363012345678901@g.us. "
                             "You can list your groups with WhatsApp Diagnostics in the WhatsApp tab.", title="Invalid Configuration")
            if g.channel == "Telegram" and not re.fullmatch(r"-\d+|@\w{4,}", g.chat_id):
                frappe.throw(f"{where}: a Telegram group chat id must be a negative number, e.g. -1001234567890.", title="Invalid Configuration")

    def validate_templates(self):
        names = set()
        for t in self.templates:
            if t.template_name in names:
                frappe.throw(f"Templates, row {t.idx}: the name {esc(t.template_name)} is already in use. Please choose a unique name.", title="Invalid Configuration")
            names.add(t.template_name)
            _check_jinja(t.message, f"Templates, row {t.idx} ({esc(t.template_name)})")

    def sync_group_notifications(self):
        """Keep one notification per group that has a document, an event and a template."""
        templates = {t.template_name: t for t in self.templates}
        wanted = {}
        for g in self.groups:
            if not (g.document_type or g.event or g.template):
                continue
            where = f"Groups, row {g.idx} ({esc(g.group_name)})"
            t = templates.get(g.template)
            if not t:
                frappe.throw(f"{where}: please select a template from the Templates tab.", title="Invalid Configuration")
            g.document_type = g.document_type or t.document_type
            if not g.document_type or not g.event:
                frappe.throw(f"{where}: please select both the document and the event.", title="Invalid Configuration")
            if t.document_type and t.document_type != g.document_type:
                frappe.throw(f"{where}: the template {esc(t.template_name)} is for {esc(t.document_type)}, "
                             f"not {esc(g.document_type)}.", title="Invalid Configuration")
            wanted[g.group_name] = g

        rows = []
        for r in self.notifications:
            if r.source_group and r.source_group not in wanted:
                continue  # the group no longer sends a template
            rows.append(r)
        self.notifications = rows
        existing = {r.source_group: r for r in rows if r.source_group}
        for name, g in wanted.items():
            r = existing.get(name) or self.append("notifications", {"source_group": name, "send_to_contact": 0})
            if r.document_type != g.document_type or r.event != g.event:
                r.title = ""  # refilled with the new document and event
            r.update({"document_type": g.document_type, "event": g.event, "template": g.template,
                      "channel": g.channel, "enabled": g.enabled})
            groups = sender._lines(r.chat_groups)
            if name not in groups:
                r.chat_groups = "\n".join(groups + [name])
            if not r.title:
                r.title = f"{name}: {g.document_type} - {g.event}"
        for i, r in enumerate(self.notifications, 1):
            r.idx = i

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
            where = f"Notifications, row {r.idx} ({esc(r.title)})"
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
                    frappe.throw(f"{where}: the Reference Date '{r.date_changed}' is not a date field.", title="Invalid Configuration")
            for f in sender.rule_filters(r):
                _check_field(meta, f[1], f"{where}: Conditions")
            for f in sender._lines(r.document_fields):
                _check_field(meta, f, f"{where}: Document Fields")
            missing = set(sender._lines(r.chat_groups)) - groups
            if missing:
                frappe.throw(f"{where}: the group(s) {esc(', '.join(missing))} do not exist. Please add them in the Groups tab.", title="Invalid Configuration")
            if r.template and r.template not in templates:
                frappe.throw(f"{where}: the template '{esc(r.template)}' does not exist. Please add it in the Templates tab.", title="Invalid Configuration")
            if not r.template and not (r.message or "").strip():
                frappe.throw(f"{where}: please select a template or enter a message.", title="Invalid Configuration")
            _check_jinja(r.message, where)
            r.send_to = _send_to_summary(r)
            if not r.send_to:
                frappe.throw(f"{where}: please select at least one recipient.", title="Invalid Configuration")

    def validate_user_alerts(self):
        templates = {t.template_name for t in self.templates}
        for r in self.user_alerts:
            if r.template and r.template not in templates:
                frappe.throw(f"User Alerts, row {r.idx}: the template '{esc(r.template)}' does not exist. Please add it in the Templates tab.", title="Invalid Configuration")
            types = sender._lines(r.types)
            doctypes = sender._lines(r.document_types)
            r.summary = (", ".join(types) or "All notifications") + " / " + (", ".join(doctypes) or "all documents")

    def set_used_in(self):
        """Show on each template and group the notifications that use it."""
        for t in self.templates:
            t.used_in = ", ".join([r.title for r in self.notifications if r.template == t.template_name]
                                  + [f"User Alert: {a.summary}" for a in self.user_alerts if a.template == t.template_name])
        for g in self.groups:
            g.used_in = ", ".join(r.title for r in self.notifications if g.group_name in sender._lines(r.chat_groups))

    @frappe.whitelist()
    def test_connection(self):
        frappe.only_for("System Manager")
        if self.mode == "Bot":
            me = sender.bot_call("getMe")
            _set("bot_username", me.get("username"))
            if self.link_method == "Polling":
                sender.bot_call("deleteWebhook")
            return result("Connection Successful",
                          f"The connection to Telegram was established successfully. Bot: <b>@{esc(me.get('username'))}</b>.")
        a, h = sender._creds(self)
        who = _run(sender._user_me(a, h, sender._session(self)))
        _set("account_status", who)
        return result("Connection Successful",
                      f"The connection to Telegram was established successfully. Account: <b>{esc(who)}</b>.")

    @frappe.whitelist()
    def set_webhook(self):
        frappe.only_for("System Manager")
        url = frappe.utils.get_url() + "/api/method/telegram_connector.api.webhook"
        if not url.startswith("https://"):
            frappe.throw("A webhook requires the site to be reachable over a public HTTPS address. "
                         "Please set Link Method to Polling if the server is internal.", title="Webhook Not Available")
        secret = self.get_password("webhook_secret", raise_exception=False)
        if not secret:
            secret = frappe.generate_hash(length=32)
            _set_secret("webhook_secret", secret)
        sender.bot_call("setWebhook", {"url": url, "secret_token": secret, "allowed_updates": '["message"]'})
        return result("Webhook Configured", f"Telegram will now deliver updates to <b>{esc(url)}</b>.")

    @frappe.whitelist()
    def send_login_code(self):
        frappe.only_for("System Manager")
        phone = sender.normalize_phone(self.login_phone, self.default_country_code)
        if not phone:
            frappe.throw("Please enter the phone number of the Telegram account in the Login Phone field.",
                         title="Phone Number Required")
        a, h = sender._creds(self)
        sess, code_hash = _run(sender._send_code(a, h, phone))
        # Keep the temporary state in the cache, not in the Single doctype,
        # because saving the form rewrites the Single values and loses the hash
        _cache().set_value(_tmp_key(), {"sess": sess, "hash": code_hash}, expires_in_sec=600)
        return result("Verification Code Sent",
                      "A verification code has been sent to the Telegram app of this account. "
                      "Please enter it in the Login Code field and click Verify &amp; Login within 10 minutes.", "blue")

    @frappe.whitelist()
    def verify_login_code(self):
        frappe.only_for("System Manager")
        phone = sender.normalize_phone(self.login_phone, self.default_country_code)
        state = _cache().get_value(_tmp_key()) or {}
        tmp, code_hash = state.get("sess"), state.get("hash")
        if not (tmp and code_hash):
            frappe.throw("No pending verification code was found, or it has expired. Please click Send Code to request a new one.",
                         title="Verification Code Expired")
        if not (self.login_code or "").strip():
            frappe.throw("Please enter the verification code in the Login Code field.", title="Verification Code Required")
        a, h = sender._creds(self)
        pw = self.get_password("two_fa_password", raise_exception=False)
        sess, who = _run(sender._verify(a, h, tmp, phone, self.login_code.strip(), code_hash, pw))
        _set_secret("session_string", sess)
        _cache().delete_value(_tmp_key())
        _set("account_status", who)
        _set("login_code", "")
        return result("Login Successful", f"The Telegram account <b>{esc(who)}</b> is now connected.")

    @frappe.whitelist()
    def send_test_message(self):
        frappe.only_for("System Manager")
        r = (self.test_recipient or "").strip()
        if not r:
            frappe.throw("Please enter a Test Recipient: a mobile number, a WhatsApp group id ending with @g.us, "
                         "or a Telegram chat id (Bot mode).", title="Recipient Required")
        text = self.test_text or "Test message from ERPNext"
        if (self.test_channel or "Telegram") == "WhatsApp":
            if not self.whatsapp_enabled:
                frappe.throw("WhatsApp is not enabled. Please enable it in the WhatsApp tab and save.",
                             title="WhatsApp Not Enabled")
            to = r if sender.is_wa_group(r) else sender.normalize_phone(r, self.default_country_code)
            sender.wa_send(to, text)
            return result("Test Message Sent", f"The test message was sent successfully via WhatsApp to <b>{esc(to)}</b>.")
        if not self.enabled:
            frappe.throw("Telegram is not enabled. Please enable it in the Telegram tab and save.",
                         title="Telegram Not Enabled")
        if self.mode == "Bot":
            to = r
            sender.send_text(r, None, text)
        else:
            to = sender.normalize_phone(r, self.default_country_code)
            sender.send_text(None, to, text)
        return result("Test Message Sent", f"The test message was sent successfully via Telegram to <b>{esc(to)}</b>.")

    @frappe.whitelist()
    def diagnose_whatsapp(self):
        """Step-by-step WhatsApp check that shows exactly which part is wrong. Never sends a message."""
        frappe.only_for("System Manager")
        import requests

        rows = []
        ok = lambda t: rows.append(("Passed", t))
        warn = lambda t: rows.append(("Warning", t))
        bad = lambda t: rows.append(("Failed", t))
        info = lambda t: rows.append(("Info", t))
        out = lambda: _diagnostics_report(rows)

        token = self.get_password("wapilot_token", raise_exception=False)
        if token:
            ok("The Wapilot API Token is set.")
        else:
            bad("The Wapilot API Token is empty. Please copy it from the Wapilot dashboard.")
        base = sender.wa_base(self) or sender.WA_CLASSIC_BASE
        m = re.match(r"(https?://[^/]+)(/.*)?$", base)
        if not m:
            bad(f"The Base URL must start with https:// (current value: {esc(base)}).")
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
                warn(f"The list of instances could not be retrieved ({type(e).__name__}). "
                     "Please copy the instance ID from the Wapilot dashboard.")
                return
            if rr.status_code == 200:
                info("Instances in your Wapilot account. Please copy the ID of the connected instance into the Base URL: "
                     f"<code>{esc(rr.text[:800])}</code>")
            else:
                warn(f"The list of instances could not be retrieved (HTTP {rr.status_code}). "
                     f"Please copy the instance ID from the Wapilot dashboard. Response: {esc(rr.text[:200])}")

        # ---------------- API v2 ----------------
        if sender.wa_is_v2(self):
            ok("Mode: Wapilot API v2. No additional package is required.")
            try:
                url, media = sender.wa_v2_urls(self)
            except frappe.ValidationError as e:
                bad(esc(str(e)).replace("\n", "<br>"))
                list_instances()
                return out()
            ok(f"Send URL: {esc(url)}")
            ok(f"Media (PDF) URL: {esc(media)}")
            try:
                sample = sender._wa_render(self.wapilot_payload, sender.WA_DEFAULT_TEXT,
                                           phone=sender._wa_fmt_phone("201000000000", self), message="Hello")
                ok(f"Message payload: <code>{esc(frappe.as_json(sample, indent=None))}</code>")
            except frappe.ValidationError as e:
                bad(esc(str(e)))
                return out()
            if not token:
                return out()
            try:
                # Empty body on purpose: the API validates it and answers with the fields it needs. Nothing is sent.
                r = requests.post(url, json={}, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"}, timeout=15)
            except Exception as e:
                bad(f"The server could not reach {esc(origin)} ({type(e).__name__}). "
                    "Please verify the internet connection, the DNS settings and the URL.")
                return out()
            ok(f"The server reached {esc(origin)} (HTTP {r.status_code}).")
            reply = esc(r.text[:300])
            if r.status_code in (401, 403):
                bad(f"Wapilot rejected the API token. Please generate a new token in the Wapilot dashboard. Response: {reply}")
            elif r.status_code == 404:
                bad("Wapilot could not find the instance. Please verify the INSTANCE ID in the Base URL and that the "
                    f"WhatsApp number is connected in Wapilot. Response: {reply}")
                list_instances()
            elif r.status_code == 405:
                bad(f"This URL does not accept message requests. Please use the full send URL ending with /send-message. Response: {reply}")
            elif r.status_code in (400, 422):
                ok("The endpoint is reachable and validated the empty test request, which is the expected result.")
                info(f"Fields expected by the API: {reply}")
                info("Next step: send a test message from the Test tab. If it fails, the error will name the field "
                     "to adjust in Advanced (API v2 payloads).")
            elif r.status_code == 200:
                warn(f"The API accepted an empty request. Response: {reply}")
            elif r.status_code >= 500:
                bad(f"Wapilot reported a server error. Please try again later. Response: {reply}")
            else:
                warn(f"Unexpected response HTTP {r.status_code}: {reply}")

            # ---- PDF / media endpoint probe (empty body, nothing is sent) ----
            root = url[: -len("/send-message")] if url.endswith("/send-message") else url
            hdr = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            found = []
            for name in ("send-media", "send-document", "send-file", "send-image", "send-attachment", "send-document-message", "send-media-message"):
                try:
                    rr = requests.post(f"{root}/{name}", json={}, headers=hdr, timeout=10)
                except Exception:
                    continue
                if rr.status_code != 404:
                    found.append(f"<b>{esc(name)}</b> (HTTP {rr.status_code}): {esc(rr.text[:200])}")
            if found:
                ok("Media (PDF) endpoints found: " + "<br>".join(found) +
                   "<br>Please enter the correct one in Media Endpoint (Advanced) if it differs from the default.")
            else:
                warn("No media endpoint was found. PDF attachments may not be delivered. "
                     "Please refer to the Wapilot documentation for the document sending URL.")

            # ---- WhatsApp groups (read only) ----
            listed = False
            for name in ("groups", "get-groups", "chats"):
                try:
                    rr = requests.get(f"{root}/{name}", headers=hdr, timeout=15)
                except Exception:
                    continue
                if rr.status_code == 200 and "@g.us" in rr.text:
                    ids = sorted(set(re.findall(r"[\w-]+@g\.us", rr.text)))
                    ok(f"{len(ids)} WhatsApp group(s) found. Please copy the required id into the Groups tab:<br>"
                       + "<br>".join(f"<code>{esc(i)}</code>" for i in ids[:50]))
                    listed = True
                    break
            if not listed:
                warn("The WhatsApp groups could not be listed automatically. Please obtain the group id (ending with @g.us) "
                     "from the Wapilot dashboard and verify it from the Test tab.")
            return out()

        # ---------------- Classic SDK ----------------
        try:
            import wapilot  # noqa: F401
            ok("The wapilot-sdk package is installed.")
        except ImportError:
            bad("The wapilot-sdk package is not installed. Please run ./env/bin/pip install wapilot-sdk, then bench restart.")
        if path:
            bad(f"The Base URL contains a path after the domain ({esc(base)}). Classic mode requires the domain only, "
                "e.g. https://app.wapilot.io. For API v2 please use https://api.wapilot.net/api/v2/&lt;INSTANCE_ID&gt;/send-message.")
            return out()
        ok(f"Mode: classic SDK. The Base URL format is valid ({esc(base)}).")
        if not token:
            return out()
        url = f"{origin}/api/contacts"
        try:
            r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=15)
        except Exception as e:
            bad(f"The server could not reach {esc(origin)} ({type(e).__name__}). Please verify the internet connection and the URL.")
            return out()
        ok(f"The server reached {esc(origin)} (HTTP {r.status_code}).")
        head = r.text[:500].lower()
        if r.status_code == 200:
            ok("The API token is valid and the API is responding.")
        elif r.status_code in (401, 403):
            bad("Wapilot rejected the API token. Please generate a new token in the Wapilot dashboard.")
        elif r.status_code == 404 and ("<html" in head or "<!doctype" in head):
            bad("The Base URL points to a web page, not to the API. Please correct the Base URL.")
        else:
            bad(f"Unexpected response HTTP {r.status_code}: {esc(r.text[:200])}")
        return out()
