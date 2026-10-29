import asyncio
import io
import re

import frappe
import requests
from frappe.utils import now_datetime


class NotLinked(Exception):
    pass


def settings():
    return frappe.get_single("Notification Hub")


def normalize_phone(phone, cc="20"):
    p = re.sub(r"[^\d+]", "", str(phone or ""))
    if not p:
        return ""
    if p.startswith("+"):
        return p
    if p.startswith("00"):
        return "+" + p[2:]
    if p.startswith("0"):
        return "+" + (cc or "20") + p[1:]
    return "+" + p



# ---------------- Readable error diagnosis ----------------
MARK = "❌"


def explain(channel, exc, status=None, body=None):
    """Turn a raw error into: WHERE the problem is + HOW to fix it + the technical detail."""
    raw = str(exc)
    if raw.startswith(MARK):
        return raw
    low = f"{raw} {body or ''}".lower()
    is_html = "<html" in low or "<!doctype" in low
    net = status is None and (
        isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout))
        or any(k in low for k in ("connection", "timed out", "timeout", "name or service", "unreachable"))
    )
    where = hint = None
    if channel == "WhatsApp":
        if "not installed" in low:
            where, hint = "Python package wapilot-sdk", "It is not installed on the server. Run: ./env/bin/pip install wapilot-sdk then bench restart."
        elif "token is not set" in low:
            where, hint = "Wapilot API Token (Notification Hub)", "The token is empty. Paste it from your Wapilot dashboard and save."
        elif status in (401, 403):
            where, hint = "Wapilot API Token", "The token is wrong, expired or has no permission. Generate a new one in the Wapilot dashboard and save it in Notification Hub."
        elif status == 405:
            where, hint = "Wapilot Base URL (wrong endpoint)", "The URL exists but does not accept this request type. For API v2 use the full send URL: https://api.wapilot.net/api/v2/<INSTANCE_ID>/send-message"
        elif status == 404 and is_html:
            where, hint = "Wapilot Base URL", "The URL reaches a website page, not the API. Classic mode: use the domain only (https://app.wapilot.io). API v2: use https://api.wapilot.net/api/v2/<INSTANCE_ID>/send-message"
        elif status == 404 or "not_found" in low:
            where, hint = "Wapilot account, instance ID or send endpoint", (
                "Wapilot says the resource was not found. Possible causes: (1) the INSTANCE ID inside the URL is wrong, "
                "(2) no WhatsApp number is connected/active in your Wapilot account, (3) the send endpoint is wrong. "
                "Click WhatsApp Diagnostics in Notification Hub."
            )
        elif status in (400, 422):
            where, hint = "Phone number or message data", (
                "Wapilot rejected the data. Check the number is in international format and the message is not empty. "
                "If the technical details name a missing field, adjust Text Message Payload in Advanced (API v2 payloads)."
            )
        elif status == 429:
            where, hint = "Wapilot rate limit", "Too many messages in a short time. Wait a bit, then click Retry."
        elif status and status >= 500:
            where, hint = "Wapilot server", "A temporary problem on their side. Try again later."
        elif net:
            where, hint = "Internet connection or Wapilot Base URL", "The server could not reach Wapilot. Check the internet/DNS and that the URL is typed correctly."
    else:
        if "unauthorized" in low or low.strip() == "not found":
            where, hint = "Bot Token", "Telegram rejected the token. Copy it again from @BotFather and save it in Notification Hub."
        elif "chat not found" in low:
            where, hint = "Customer link (Chat ID)", "The customer has not pressed Start on the bot, or the Chat ID is wrong. Send them the link from Telegram Link."
        elif "blocked by the user" in low:
            where, hint = "The customer", "The customer blocked the bot. They must unblock it and press Start again."
        elif "too many requests" in low or "flood" in low:
            where, hint = "Telegram rate limit", "Telegram limited sending temporarily. Wait the time shown in the details, then click Retry."
        elif "phonenumberinvalid" in low:
            where, hint = "Phone number", "The number is not valid. Check it is complete and in international format."
        elif "apiidinvalid" in low or "api_id" in low or "api_hash" in low:
            where, hint = "api_id / api_hash", "The keys are wrong. Copy them again from my.telegram.org."
        elif any(k in low for k in ("authkey", "session", "not authorized", "sessionrevoked")):
            where, hint = "Telegram account session", "The session expired or was revoked. Log the account in again (Send Code, then Verify & Login)."
        elif net:
            where, hint = "Connection to Telegram", "The server could not reach Telegram. Check the internet or proxy."
    if not where:
        where, hint = "Unknown", "See the technical details below and send them to your system administrator."
    detail = raw if not body or is_html else f"{raw} | {str(body)[:300]}"
    return f"{MARK} Problem in: {where}\nCause and fix: {hint}\nTechnical details: {detail[:600]}"


def notify_failure(log, status, error):
    """Tell the people who care that a send failed: bell notification + popup if they are online."""
    if status == "Sent" and not error:
        return
    try:
        users = set(frappe.get_all("Has Role", filters={"role": "System Manager", "parenttype": "User"}, pluck="parent"))
        users.add(frappe.session.user)
        users = [u for u in users if u != "Guest" and frappe.db.get_value("User", u, "enabled")]
        warn = status == "Sent"
        subject = f"{log.channel or 'Telegram'}: {'Sent with warning' if warn else status} — {log.reference_doctype} {log.reference_name}"
        html = frappe.utils.escape_html(error or "").replace("\n", "<br>")
        for u in users:
            frappe.get_doc({
                "doctype": "Notification Log", "for_user": u, "type": "Alert", "subject": subject,
                "email_content": html, "document_type": "Hub Message Log", "document_name": log.name,
            }).insert(ignore_permissions=True)
            frappe.publish_realtime("msgprint", {"title": subject, "message": html,
                                                 "indicator": "orange" if warn else "red"}, user=u)
        frappe.db.commit()
    except Exception:
        frappe.logger("telegram").exception("notify_failure failed")


# ---------------- Bot API ----------------
def bot_call(method, data=None, files=None):
    token = settings().get_password("bot_token", raise_exception=False)
    if not token:
        raise frappe.ValidationError("Bot Token is not set")
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/{method}", data=data, files=files, timeout=30)
        j = r.json()
    except Exception as e:
        raise frappe.ValidationError(explain("Telegram", Exception(str(e).replace(token, "***"))))
    if not j.get("ok"):
        raise frappe.ValidationError(explain("Telegram", Exception(str(j.get("description") or "Telegram error")), r.status_code))
    return j["result"]


def make_deep_link(token):
    u = settings().bot_username
    return f"https://t.me/{u}?start={token}" if u and token else ""


# ---------------- User account (Telethon) ----------------
def run_async(coro):
    return asyncio.run(coro)


def _creds(s):
    if not s.api_id:
        raise frappe.ValidationError("api_id is not set")
    api_hash = s.get_password("api_hash", raise_exception=False)
    if not api_hash:
        raise frappe.ValidationError("api_hash is not set")
    try:
        return int(str(s.api_id).strip()), api_hash
    except ValueError:
        raise frappe.ValidationError("api_id must contain digits only")


def _session(s):
    sess = s.get_password("session_string", raise_exception=False)
    if not sess:
        raise frappe.ValidationError("The account is not logged in yet (Send Code, then Verify)")
    return sess


async def _connect(api_id, api_hash, session):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    c = TelegramClient(StringSession(session), api_id, api_hash)
    await c.connect()
    return c


async def _resolve(c, phone):
    from telethon.tl.functions.contacts import ImportContactsRequest
    from telethon.tl.types import InputPhoneContact

    res = await c(ImportContactsRequest([InputPhoneContact(0, phone, "ERP", "")]))
    if not res.users:
        raise NotLinked("This number is not registered on Telegram, or its privacy settings prevent access")
    return res.users[0]


async def _user_send(api_id, api_hash, session, phone, text, pdf, pdf_name):
    c = await _connect(api_id, api_hash, session)
    try:
        if not await c.is_user_authorized():
            raise frappe.ValidationError("The session has expired. Please log in to the account again")
        u = await _resolve(c, phone)
        await c.send_message(u, text)
        if pdf:
            f = io.BytesIO(pdf)
            f.name = pdf_name
            await c.send_file(u, f)
        return {"id": u.id, "username": u.username or ""}
    finally:
        await c.disconnect()


async def _user_resolve(api_id, api_hash, session, phone):
    c = await _connect(api_id, api_hash, session)
    try:
        u = await _resolve(c, phone)
        return {"id": u.id, "username": u.username or ""}
    finally:
        await c.disconnect()


async def _user_me(api_id, api_hash, session):
    c = await _connect(api_id, api_hash, session)
    try:
        if not await c.is_user_authorized():
            raise frappe.ValidationError("The session is not logged in")
        me = await c.get_me()
        return f"{me.first_name or ''} ({me.phone})"
    finally:
        await c.disconnect()


async def _send_code(api_id, api_hash, phone):
    c = await _connect(api_id, api_hash, "")
    try:
        sent = await c.send_code_request(phone)
        return c.session.save(), sent.phone_code_hash
    finally:
        await c.disconnect()


async def _verify(api_id, api_hash, session, phone, code, code_hash, pw):
    from telethon.errors import SessionPasswordNeededError

    c = await _connect(api_id, api_hash, session)
    try:
        try:
            await c.sign_in(phone=phone, code=code, phone_code_hash=code_hash)
        except SessionPasswordNeededError:
            if not pw:
                raise frappe.ValidationError("This account has Two-Step Verification enabled: enter the password in the Two Fa Password field")
            await c.sign_in(password=pw)
        me = await c.get_me()
        return c.session.save(), f"{me.first_name or ''} ({me.phone})"
    finally:
        await c.disconnect()


def resolve_user(phone):
    s = settings()
    a, h = _creds(s)
    return run_async(_user_resolve(a, h, _session(s), phone))


# ---------------- Unified send ----------------
def send_text(chat_id, phone, text, pdf=None, pdf_name="document.pdf"):
    s = settings()
    text = (text or "")[:4096]
    if s.mode == "Bot":
        bot_call("sendMessage", {"chat_id": chat_id, "text": text})
        if pdf:
            bot_call("sendDocument", {"chat_id": chat_id}, files={"document": (pdf_name, pdf)})
        return {"id": chat_id}
    a, h = _creds(s)
    return run_async(_user_send(a, h, _session(s), phone, text, pdf, pdf_name))


# ---------------- Links ----------------
def find_link(party_type, party, phone):
    if party_type and party:
        n = frappe.db.get_value("Telegram Link", {"party_type": party_type, "party": party}, "name")
        if n:
            return frappe.get_doc("Telegram Link", n)
    if phone:
        n = frappe.db.get_value("Telegram Link", {"mobile_no": phone}, "name")
        if n:
            return frappe.get_doc("Telegram Link", n)
    return None


def ensure_link(party_type, party, phone):
    link = find_link(party_type, party, phone)
    if link:
        return link
    link = frappe.get_doc({
        "doctype": "Telegram Link", "party_type": party_type, "party": party,
        "mobile_no": phone, "status": "Pending",
    })
    link.insert(ignore_permissions=True)
    return link


def process_update(update):
    msg = update.get("message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or not text.startswith("/start"):
        return
    parts = text.split(maxsplit=1)
    token = parts[1].strip() if len(parts) > 1 else ""
    name = frappe.db.get_value("Telegram Link", {"token": token}, "name") if token else None
    if not name:
        bot_call("sendMessage", {"chat_id": chat_id, "text": "Hello. To link your account, please use the personal link sent to you by the company."})
        return
    frappe.db.set_value("Telegram Link", name, {
        "chat_id": str(chat_id), "telegram_username": chat.get("username") or "",
        "status": "Linked", "last_error": "",
    })
    bot_call("sendMessage", {"chat_id": chat_id, "text": "Your account has been linked successfully. You will receive your invoices and notifications here."})


def poll_updates():
    s = settings()
    if not (s.enabled and s.mode == "Bot" and s.link_method == "Polling"):
        return
    if not s.get_password("bot_token", raise_exception=False):
        return
    try:
        updates = bot_call("getUpdates", {
            "offset": (s.last_update_id or 0) + 1, "timeout": 0, "allowed_updates": '["message"]',
        })
    except Exception as e:
        frappe.logger("telegram").warning(f"poll failed: {e}")
        return
    last = None
    for u in updates:
        last = u["update_id"]
        try:
            process_update(u)
        except Exception:
            frappe.logger("telegram").exception("process_update failed")
    if last:
        frappe.db.set_single_value("Notification Hub", "last_update_id", last)
        frappe.db.commit()


# ---------------- Notifications ----------------
def rule_matches(rule, doc):
    """True when every row of the Conditions table and the optional Python condition hold."""
    meta = frappe.get_meta(doc.doctype)
    for c in rule.get("conditions") or []:
        if not _condition_holds(doc, meta, c):
            return False
    if rule.get("condition"):
        return bool(frappe.safe_eval(rule.condition, None, {"doc": doc}))
    return True


def _condition_holds(doc, meta, c):
    from frappe.utils import compare

    op, actual, want = c.operator or "=", doc.get(c.fieldname), (c.value or "").strip()
    df = meta.get_field(c.fieldname)
    fieldtype = df.fieldtype if df else _guess_fieldtype(actual)
    if op in ("is set", "is not set"):
        return compare(actual, "is", op.split()[-1] if op == "is set" else "not set")
    if op in ("in", "not in"):
        return compare(actual, op, [v.strip() for v in want.split(",")], fieldtype)
    if op in ("like", "not like") and "%" not in want:
        want = f"%{want}%"
    return compare(actual, op, want, fieldtype)


def _guess_fieldtype(value):
    """Standard fields (docstatus, idx, creation...) have no docfield: cast by the value's type."""
    import datetime
    from decimal import Decimal

    if isinstance(value, bool | int | float | Decimal):
        return "Float"
    if isinstance(value, datetime.datetime):
        return "Datetime"
    if isinstance(value, datetime.date):
        return "Date"
    return None


def template_context(doc, extra=None):
    """Values available in a rule's message besides doc."""
    extra = extra or {}
    user = extra.get("changed_by") or frappe.session.user
    return {
        "doc": doc,
        "changed_by": frappe.db.get_value("User", user, "full_name") or user,
        "changed_by_user": user,
        "old_value": extra.get("old_value", ""),
        "new_value": extra.get("new_value", ""),
        "field_label": extra.get("field_label", ""),
    }


def _contact_target(rule, doc):
    """The customer / party of the document (the original recipient of a rule)."""
    party_type = rule.party_doctype
    party = doc.get(rule.party_field) if rule.party_field else None
    p_doc = doc.get(rule.mobile_field) if rule.mobile_field else None
    p_party = None
    if party_type and party and rule.party_mobile_field:
        p_party = frappe.db.get_value(party_type, party, rule.party_mobile_field)
    phone = (p_party or p_doc) if rule.prefer_party_mobile else (p_doc or p_party)
    return {"party_type": party_type if party else None, "party": party, "mobile_no": phone}


def _user_target(user):
    return {"party_type": "User", "party": user, "mobile_no": frappe.db.get_value("User", user, "mobile_no")}


def _recipient_targets(row, doc):
    t = row.recipient_type
    if t == "User" and row.user:
        return [_user_target(row.user)]
    if t == "Role" and row.role:
        users = frappe.get_all("Has Role", filters={"role": row.role, "parenttype": "User"}, pluck="parent")
        users = frappe.get_all("User", filters={"name": ("in", users), "enabled": 1, "user_type": "System User"},
                               pluck="name") if users else []
        return [_user_target(u) for u in users if u not in ("Administrator", "Guest")]
    if t == "Mobile Number" and row.mobile_no:
        return [{"party_type": None, "party": None, "mobile_no": row.mobile_no}]
    if t == "Document Field" and row.document_field:
        v = doc.get(row.document_field)
        if not v:
            return []
        if frappe.db.exists("User", v):
            return [_user_target(v)]
        return [{"party_type": None, "party": None, "mobile_no": v}]
    return []


def process_rule(rule, ref_doctype, ref_name, force=False, channels=None, extra=None, contact_only=False):
    """Create + deliver the message(s) for a rule. Returns the list of Hub Message Log names.

    force=True: manual send (ignores the conditions and raises if no channel is enabled).
    channels: limit to specific channels (e.g. ["WhatsApp"]); default = the rule's channel(s).
    extra: event details for the message (changed_by, old_value, new_value, field_label).
    contact_only: send only to the document's customer / contact (Notify Customer button).
    """
    if isinstance(rule, str):
        rule = frappe.get_doc("Hub Notification Rule", rule)
    doc = frappe.get_doc(ref_doctype, ref_name)
    if not force:
        try:
            if not rule_matches(rule, doc):
                return []
        except Exception:
            frappe.log_error(title="Notification Hub: bad condition", message=f"{rule.name}\n{frappe.get_traceback()}")
            return []
    active = [c for c in (channels or rule_channels(rule)) if channel_enabled(c)]
    if not active and not (rule.get("groups") and not contact_only):
        if force:
            frappe.throw("The selected channel is not enabled in Notification Hub")
        return []
    cc = settings().default_country_code
    message = frappe.render_template(rule.message, template_context(doc, extra))

    people = []
    # a rule saved before "send_to_document_contact" existed, or the built-in preset, sends to the contact
    if rule.get("send_to_document_contact") in (None, 1) or contact_only:
        people.append(_contact_target(rule, doc))
    if not contact_only:
        for row in rule.get("recipients") or []:
            people.extend(_recipient_targets(row, doc))

    targets, seen = [], set()
    for ch in active:
        for p in people:
            p = dict(p, mobile_no=normalize_phone(p["mobile_no"], cc))
            key = (ch, p["party_type"], p["party"]) if p["party"] else (ch, p["mobile_no"])
            if key not in seen:
                seen.add(key)
                targets.append(dict(p, channel=ch, chat_id=None))
    if not contact_only:
        for g in rule.get("groups") or []:
            grp = frappe.db.get_value("Hub Chat Group", g.group, ["channel", "chat_id", "enabled"], as_dict=True)
            if grp and grp.enabled and channel_enabled(grp.channel) and (grp.channel, grp.chat_id) not in seen:
                seen.add((grp.channel, grp.chat_id))
                targets.append({"channel": grp.channel, "chat_id": grp.chat_id,
                                "party_type": None, "party": None, "mobile_no": ""})

    names = []
    for t in targets:
        log = frappe.get_doc({
            "doctype": "Hub Message Log", "notification": rule.name, "status": "Queued", "channel": t["channel"],
            "reference_doctype": ref_doctype, "reference_name": ref_name,
            "party_type": t["party_type"], "party": t["party"],
            "mobile_no": t["mobile_no"], "chat_id": t["chat_id"], "message": message,
            "attach_print": rule.attach_print, "print_format": rule.print_format,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        deliver(log.name, notify=not force)
        names.append(log.name)
    return names


def run_date_rules():
    """Daily: rules with event Days Before / Days After."""
    from frappe.utils import add_days, nowdate

    if not enabled_channels():
        return
    for rule in frappe.get_all("Hub Notification Rule", pluck="name",
                               filters={"enabled": 1, "event": ("in", ("Days Before", "Days After"))}):
        rule = frappe.get_doc("Hub Notification Rule", rule)
        days = rule.days_in_advance or 0
        day = add_days(nowdate(), days if rule.event == "Days Before" else -days)
        meta = frappe.get_meta(rule.document_type)
        if not meta.has_field(rule.date_changed):
            continue
        filters = {rule.date_changed: day}
        if meta.is_submittable:
            filters["docstatus"] = ("<", 2)
        if meta.get_field(rule.date_changed).fieldtype == "Datetime":
            filters[rule.date_changed] = ("between", (day, day))
        for name in frappe.get_all(rule.document_type, filters=filters, pluck="name"):
            try:
                process_rule(rule, rule.document_type, name)
            except Exception:
                frappe.log_error(title="Notification Hub: date rule", message=f"{rule.name} {name}\n{frappe.get_traceback()}")


def deliver(log_name, notify=False):
    log = frappe.get_doc("Hub Message Log", log_name)
    if (log.channel or "Telegram") == "WhatsApp":
        return _deliver_whatsapp(log, notify)
    s = settings()
    status, error, chat_id = "Sent", "", log.chat_id
    try:
        if not s.enabled:
            raise NotLinked("Notification Hub is not enabled")
        pdf = None
        if log.attach_print:
            try:
                pdf = frappe.get_print(log.reference_doctype, log.reference_name,
                                       print_format=log.print_format or None, as_pdf=True)
            except Exception as e:
                error = f"Could not generate PDF: {e}"
        link = find_link(log.party_type, log.party, log.mobile_no)
        pdf_name = f"{log.reference_name}.pdf"
        if s.mode == "Bot" and not log.party_type and log.chat_id:
            # Group message: no Telegram Link needed, send straight to the group chat id
            chat_id = log.chat_id
            send_text(chat_id, None, log.message, pdf, pdf_name)
        elif s.mode == "Bot":
            if not (link and link.status == "Linked" and link.chat_id):
                link = link or ensure_link(log.party_type, log.party, log.mobile_no)
                raise NotLinked(f"The customer has not linked their account yet. Link: {link.deep_link}")
            chat_id = link.chat_id
            send_text(chat_id, None, log.message, pdf, pdf_name)
        else:
            if not log.party_type and log.chat_id and not log.mobile_no:
                raise NotLinked("Sending to a Telegram group needs Mode = Bot in Notification Hub")
            if not log.mobile_no:
                raise NotLinked("No mobile number found")
            info = send_text(None, log.mobile_no, log.message, pdf, pdf_name)
            chat_id = str(info["id"])
            link = link or ensure_link(log.party_type, log.party, log.mobile_no)
            link.db_set({"chat_id": chat_id, "telegram_username": info.get("username") or "",
                         "status": "Linked", "last_error": ""})
    except NotLinked as e:
        status, error = "Not Linked", str(e)
    except Exception as e:
        status, error = "Failed", explain("Telegram", e)
    log.db_set({"status": status, "error": error, "chat_id": chat_id or "", "mode": s.mode,
                "sent_on": now_datetime() if status == "Sent" else None})
    frappe.db.commit()
    if notify:
        notify_failure(log, status, error)


# ---------------- Channels ----------------
CHANNELS = ("Telegram", "WhatsApp")


def channel_enabled(channel, s=None):
    s = s or settings()
    return bool(s.whatsapp_enabled if channel == "WhatsApp" else s.enabled)


def enabled_channels():
    s = settings()
    return [c for c in CHANNELS if channel_enabled(c, s)]


def rule_channels(rule):
    c = rule.get("channel") or "Telegram"
    return list(CHANNELS) if c == "Both" else [c]


# ---------------- WhatsApp (Wapilot) ----------------
WA_CLASSIC_BASE = "https://app.wapilot.io"
WA_DEFAULT_TEXT = '{"chat_id": "{phone}", "text": "{message}"}'
WA_DEFAULT_MEDIA = '{"chat_id": "{phone}", "media_type": "document", "media_url": "{media_url}", "file_name": "{file_name}"}'


_WA_GROUP_V2 = ("❌ Problem in: Wapilot Base URL\nCause and fix: Sending to WhatsApp groups needs Wapilot API v2. "
                "Set Wapilot Base URL to https://api.wapilot.net/api/v2/<INSTANCE_ID>/send-message")


def wa_base(s=None):
    s = s or settings()
    return (s.wapilot_base_url or "").strip().rstrip("/")


def wa_is_v2(s=None):
    """API v2 = api.wapilot.net/api/v2/<instance>/send-message (different from the classic SDK API)."""
    b = wa_base(s)
    return "/api/v2" in b or "api.wapilot.net" in b


def wa_v2_urls(s=None):
    """Return (text_url, media_url). Raises a readable error if the instance id is missing."""
    s = s or settings()
    b = wa_base(s)
    m = re.search(r"/api/v2/([^/]+)", b)
    # "instances" is the API's list path and "<INSTANCE_ID>" the docs placeholder: neither is a real instance id
    if not m or m.group(1).lower() in ("instances", "instance", "send-message") or "<" in m.group(1) or "%3c" in m.group(1).lower():
        raise frappe.ValidationError(
            "❌ Problem in: Wapilot Base URL (instance ID)\n"
            "Cause and fix: The URL does not contain your real instance ID. Copy the instance ID from your Wapilot "
            "dashboard and use: https://api.wapilot.net/api/v2/<INSTANCE_ID>/send-message"
            f"\nTechnical details: current Base URL is {b or '(empty)'}"
        )
    if b.endswith("/send-message"):
        text_url, root = b, b[: -len("/send-message")]
    else:
        text_url, root = b + "/send-message", b
    media_url = (s.wapilot_media_endpoint or "").strip() or f"{root}/send-media"
    return text_url, media_url


def is_wa_group(chat_id):
    return str(chat_id or "").strip().endswith("@g.us")


def _wa_fmt_phone(phone, s=None):
    s = s or settings()
    p = str(phone or "").strip()
    if is_wa_group(p):
        return p  # group ids are sent exactly as they are
    if (s.wapilot_phone_format or "").startswith("With plus"):
        return p if p.startswith("+") else "+" + p.lstrip("+")
    return p.lstrip("+")


def _wa_render(template, default, **values):
    """Parse the JSON template and substitute placeholders inside string values only,
    so quotes/new lines in the message can never break the JSON."""
    import json

    try:
        data = json.loads((template or "").strip() or default)
    except ValueError as e:
        raise frappe.ValidationError(f"The payload in Advanced (API v2 payloads) is not valid JSON: {e}")

    def walk(x):
        if isinstance(x, str):
            for k, v in values.items():
                x = x.replace("{" + k + "}", str(v))
            return x
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        return x

    return walk(data)


def _wa_v2_post(url, payload):
    s = settings()
    token = s.get_password("wapilot_token", raise_exception=False)
    if not token:
        raise frappe.ValidationError("Wapilot API token is not set")
    try:
        r = requests.post(
            url, json=payload, timeout=30,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    except Exception as e:
        raise frappe.ValidationError(explain("WhatsApp", Exception(str(e).replace(token, "***"))))
    try:
        j = r.json()
    except ValueError:
        j = None
    failed = r.status_code >= 400 or (
        isinstance(j, dict) and (j.get("success") is False or str(j.get("status", "")).lower() in ("error", "failed"))
    )
    if failed:
        msg = (j.get("message") or j.get("error") or r.text[:300]) if isinstance(j, dict) else r.text[:300]
        raise frappe.ValidationError(explain("WhatsApp", Exception(str(msg)), r.status_code, r.text[:500]))
    return j if isinstance(j, dict) else {"raw": r.text[:200]}


def _wa_client():
    """Classic Wapilot SDK client (only used when the Base URL is NOT API v2)."""
    s = settings()
    token = s.get_password("wapilot_token", raise_exception=False)
    if not token:
        raise frappe.ValidationError("Wapilot API token is not set")
    try:
        from wapilot import WapilotSDK
    except ImportError:
        raise frappe.ValidationError(
            "The wapilot-sdk package is not installed. Run in the bench env: pip install wapilot-sdk"
        )
    base = wa_base(s)
    return WapilotSDK(token=token, base_url=base) if base else WapilotSDK(token=token)


def _wa_call(fn, payload):
    try:
        res = fn(payload)
    except Exception as e:
        resp = getattr(e, "response", None)
        status = resp.status_code if resp is not None else None
        body = (getattr(resp, "text", "") or "")[:500] if resp is not None else None
        raise frappe.ValidationError(explain("WhatsApp", e, status, body))
    if isinstance(res, dict) and (
        res.get("success") is False or str(res.get("status", "")).lower() in ("error", "failed")
    ):
        raise frappe.ValidationError(explain("WhatsApp", Exception(str(res.get("message") or res)), None, str(res)))
    return res


def wa_send(phone, text):
    s = settings()
    text = (text or "")[:4096]
    if wa_is_v2(s):
        url, _ = wa_v2_urls(s)
        payload = _wa_render(s.wapilot_payload, WA_DEFAULT_TEXT, phone=_wa_fmt_phone(phone, s), message=text)
        return _wa_v2_post(url, payload)
    if is_wa_group(phone):
        raise frappe.ValidationError(_WA_GROUP_V2)
    c = _wa_client()
    return _wa_call(c.send_message, {"phone": phone, "message": text})


def wa_send_pdf(phone, url, file_name):
    s = settings()
    if wa_is_v2(s):
        _, media = wa_v2_urls(s)
        payload = _wa_render(s.wapilot_media_payload, WA_DEFAULT_MEDIA,
                             phone=_wa_fmt_phone(phone, s), media_url=url, file_name=file_name)
        return _wa_v2_post(media, payload)
    if is_wa_group(phone):
        raise frappe.ValidationError(_WA_GROUP_V2)
    c = _wa_client()
    return _wa_call(c.send_media_message, {
        "phone": phone, "media_type": "document", "media_url": url, "file_name": file_name,
    })


def _brief(exc):
    """Short, readable reason from an explain() text: no technical details."""
    t = str(exc)
    where = re.search(r"Problem in: (.+)", t)
    fix = re.search(r"Cause and fix: (.+)", t)
    if where and fix:
        return f"{where.group(1).strip()}. {fix.group(1).strip()}"
    return t.splitlines()[0][:200]


def _site_is_public():
    """Wapilot downloads the PDF from a URL, so the site address must be reachable from the internet."""
    import ipaddress
    from urllib.parse import urlparse

    host = (urlparse(frappe.utils.get_url()).hostname or "").lower()
    if not host or host in ("localhost",) or host.endswith((".local", ".localhost", ".lan", ".internal")) or "." not in host:
        return False
    try:
        ip = ipaddress.ip_address(host)
        return not (ip.is_private or ip.is_loopback or ip.is_link_local)
    except ValueError:
        return True


def _public_pdf_url(log, pdf):
    """Wapilot fetches media from a URL, so the PDF is stored as a public file with an
    unguessable name and removed by cleanup_public_pdfs() after 2 days."""
    base = re.sub(r"[^\w.-]", "-", str(log.reference_name))
    f = frappe.get_doc({
        "doctype": "File", "file_name": f"{base}-{frappe.generate_hash(length=10)}.pdf",
        "content": pdf, "is_private": 0,
        "attached_to_doctype": "Hub Message Log", "attached_to_name": log.name,
    }).insert(ignore_permissions=True)
    return frappe.utils.get_url(f.file_url)


def _deliver_whatsapp(log, notify=False):
    s = settings()
    status, error, quiet = "Sent", "", False
    try:
        if not s.whatsapp_enabled:
            raise NotLinked("WhatsApp is not enabled in Notification Hub")
        to = log.mobile_no or log.chat_id  # chat_id = WhatsApp group (…@g.us)
        if not to:
            raise NotLinked("No mobile number found")
        wa_send(to, log.message)
        if log.attach_print:
            if not _site_is_public():
                # expected on an internal server: record it, but do not raise an alert for every message
                error = ("Message delivered. PDF not attached: the site address is not reachable from the internet, "
                         "which WhatsApp needs to download the file.")
                quiet = True
            else:
                try:
                    pdf = frappe.get_print(log.reference_doctype, log.reference_name,
                                           print_format=log.print_format or None, as_pdf=True)
                    wa_send_pdf(to, _public_pdf_url(log, pdf), f"{log.reference_name}.pdf")
                except Exception as e:
                    error = f"Message delivered. PDF not attached: {_brief(e)}"
    except NotLinked as e:
        status, error = "Not Linked", str(e)
    except Exception as e:
        status, error = "Failed", explain("WhatsApp", e)
    log.db_set({"status": status, "error": error, "chat_id": log.chat_id or log.mobile_no or "", "mode": "Wapilot",
                "sent_on": now_datetime() if status == "Sent" else None})
    frappe.db.commit()
    if notify and not quiet:
        notify_failure(log, status, error)


def cleanup_public_pdfs():
    from frappe.utils import add_days

    old = frappe.get_all("File", filters={
        "attached_to_doctype": "Hub Message Log", "is_private": 0,
        "creation": ("<", add_days(now_datetime(), -2)),
    }, pluck="name")
    for n in old:
        frappe.delete_doc("File", n, ignore_permissions=True, force=True)
        