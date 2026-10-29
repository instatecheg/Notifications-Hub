import hmac
import frappe
from telegram_connector import sender


@frappe.whitelist(allow_guest=True, methods=["POST"])
def webhook():
    s = sender.settings()
    got = frappe.get_request_header("X-Telegram-Bot-Api-Secret-Token") or ""
    want = s.get_password("webhook_secret", raise_exception=False) or ""
    if not want or not hmac.compare_digest(got, want):
        frappe.local.response["http_status_code"] = 403
        return "forbidden"
    sender.process_update(frappe.parse_json(frappe.request.data))
    return "ok"


@frappe.whitelist()
def get_party_mobile(party_type, party):
    frappe.has_permission(party_type, "read", party, throw=True)
    meta = frappe.get_meta(party_type)
    for f in ("mobile_no", "mobile", "phone", "contact_mobile"):
        if meta.has_field(f):
            v = frappe.db.get_value(party_type, party, f)
            if v:
                return v


@frappe.whitelist()
def get_or_create_link(party_type, party):
    frappe.has_permission("Telegram Link", "create", throw=True)
    link = sender.find_link(party_type, party, None)
    if not link:
        link = sender.ensure_link(party_type, party, get_party_mobile(party_type, party))
    return link.name


@frappe.whitelist()
def get_enabled_channels():
    return sender.enabled_channels()


@frappe.whitelist()
def get_fields(doctype):
    """Fields of a DocType for the no-code pickers in Notification Hub."""
    frappe.has_permission("Notification Hub", "write", throw=True)
    skip = {"Section Break", "Column Break", "Tab Break", "HTML", "Button", "Table", "Table MultiSelect",
            "Image", "Fold", "Heading", "Attach Image", "Signature", "Geolocation"}
    std = [{"value": "name", "label": "ID (name)", "fieldtype": "Data"},
           {"value": "owner", "label": "Created By (owner)", "fieldtype": "Link"},
           {"value": "modified_by", "label": "Last Updated By (modified_by)", "fieldtype": "Link"},
           {"value": "docstatus", "label": "Document Status (docstatus: 0 Draft, 1 Submitted, 2 Cancelled)", "fieldtype": "Int"}]
    out = [{"value": f.fieldname, "label": f"{f.label or f.fieldname} ({f.fieldname})", "fieldtype": f.fieldtype}
           for f in frappe.get_meta(doctype).fields if f.fieldtype not in skip]
    return out + std


@frappe.whitelist()
def get_user_telegram_link(user):
    """Personal Telegram link a user opens once (Start) to receive User Alerts in Bot mode."""
    frappe.has_permission("Notification Hub", "write", throw=True)
    link = sender.ensure_link("User", user, frappe.db.get_value("User", user, "mobile_no"))
    return {"status": link.status, "deep_link": link.deep_link, "name": link.name}


@frappe.whitelist()
def get_preset(doctype):
    """Ready-made recipient fields + message for a new notification in Notification Hub."""
    frappe.has_permission("Notification Hub", "write", throw=True)
    from telegram_connector import presets

    return presets.get_preset(doctype)


@frappe.whitelist()
def preview_message(doctype, name, message):
    """Render a message template against a real document (Preview button)."""
    frappe.has_permission("Notification Hub", "write", throw=True)
    frappe.has_permission(doctype, "read", name, throw=True)
    sample = {"old_value": "(old value)", "new_value": "(new value)", "field_label": "(field)"}
    return frappe.render_template(message or "", sender.template_context(frappe.get_doc(doctype, name), sample))


def _pick_rule(doctype, channel):
    rules = [r for r in sender.settings().notifications
             if r.enabled and r.document_type == doctype and (r.channel or "Telegram") in (channel, "Both")]
    if rules:
        rules.sort(key=lambda r: r.event != "Submit")  # prefer the Submit notification
        return rules[0]
    if doctype == "Sales Invoice":
        # Nothing configured: fall back to the built-in default so the button works out of the box
        from telegram_connector import presets

        return frappe._dict(presets.get_preset("Sales Invoice"), title=None, print_format=None)
    frappe.throw(f"No enabled notification for {doctype} in Notification Hub > Notifications. Please add one first.")


@frappe.whitelist()
def notify_customer(doctype, name, channel=None):
    """Notify Customer button: send the document now via Telegram, WhatsApp or both."""
    frappe.has_permission(doctype, "read", name, throw=True)
    enabled = sender.enabled_channels()
    if not enabled:
        frappe.throw("No channel is enabled. Enable Telegram or WhatsApp in Notification Hub.")
    if channel in (None, "", "Both"):
        targets = enabled
    elif channel in enabled:
        targets = [channel]
    else:
        frappe.throw(f"{channel} is not enabled in Notification Hub")
    results = []
    for ch in targets:
        rule = _pick_rule(doctype, ch)
        for log in sender.process_rule(rule, doctype, name, force=True, channels=[ch], contact_only=True):
            st, err = frappe.db.get_value("Hub Message Log", log, ["status", "error"])
            results.append({"channel": ch, "status": st, "error": err, "log": log})
    return {"results": results}
