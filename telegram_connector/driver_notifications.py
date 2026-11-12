"""Send Delivery Trip / Transportation Request details to the assigned Driver on Telegram.

Recipients of every document:
- the assigned Driver (if set)
- the user who created the document (doc.owner)

For each recipient:
- First save (or new assignment)          -> full details are sent.
- Later saves / update-after-submit       -> only the changes are sent.
- If nothing was ever delivered to that recipient yet (e.g. not linked on Telegram),
  the full details are sent again on the next save.
- Driver changed                          -> previous driver gets a "reassigned" notice.
Every send is also written to the document's Activity timeline (who, to whom, by whom).
"""

import frappe
from frappe.utils import escape_html

from telegram_connector import sender

DRIVER_DOCTYPE = "Driver"
USER_DOCTYPE = "User"
GROUP = "Group"  # marker for the Telegram group recipient (not a DocType)
STOP_DOCTYPE = "Delivery Stop"

# Per DocType: fields shown in the message and tracked for changes, and whether it has a stops table
DOCTYPE_CONFIG = {
    "Delivery Trip": {
        "fields": ["company", "vehicle", "departure_time", "total_estimated_distance"],
        "stops": True,
    },
    "Transportation Request": {
        "fields": ["customer", "route", "departure_time", "note"],
        "stops": False,
    },
}
STOP_FIELDS = ["customer", "address", "delivery_note", "estimated_arrival"]


def on_update(doc, method=None):
    f = frappe.flags
    if f.in_import or f.in_patch or f.in_install or f.in_migrate:
        return
    if doc.doctype not in DOCTYPE_CONFIG:
        return
    channels = _driver_channels()
    if not channels:
        return

    before = doc.get_doc_before_save()
    driver = doc.get("driver")
    old_driver = before.get("driver") if before else None

    if old_driver and old_driver != driver:
        _enqueue(doc.doctype, doc.name, DRIVER_DOCTYPE, old_driver,
                 reassigned_message(doc), channels, "Reassignment notice")

    recipients = []
    if driver:
        recipients.append((DRIVER_DOCTYPE, driver))
    if doc.owner:
        recipients.append((USER_DOCTYPE, doc.owner))

    # Telegram group (set in Notification Hub > Group Chat ID)
    group_id = _group_id()
    if group_id:
        recipients.append((GROUP, group_id))

    seen = set()
    for party_type, party in recipients:
        if (party_type, party) in seen:
            continue
        seen.add((party_type, party))

        new_assignment = party_type == DRIVER_DOCTYPE and (not before or old_driver != driver)
        if party_type == GROUP:
            full_needed = not before or not _group_sent_before(doc.doctype, doc.name, party)
        else:
            full_needed = not before or new_assignment or not _sent_before(doc.doctype, doc.name, party_type, party)

        if full_needed:
            if party_type == DRIVER_DOCTYPE:
                title = f"{doc.doctype} assigned to you"
            else:
                title = f"{doc.doctype} details"
            text = full_message(doc, title)
            kind = "Details"
        else:
            changes = describe_changes(doc, before)
            if not changes:
                continue
            text = update_message(doc, changes)
            kind = "Update"

        _enqueue(doc.doctype, doc.name, party_type, party, text, channels, kind)


# ---------------- Delivery ----------------
def _driver_channels():
    """Driver messages go out on Telegram only for now.
    WhatsApp is commented out on purpose; to enable it later, use: return sender.enabled_channels()
    """
    # return sender.enabled_channels()  # WhatsApp: disabled for now
    return ["Telegram"] if sender.channel_enabled("Telegram") else []


def _enqueue(doctype, name, party_type, party, text, channels, kind):
    frappe.enqueue(
        "telegram_connector.driver_notifications.send_to_party",
        queue="short",
        enqueue_after_commit=True,
        doctype=doctype,
        name=name,
        party_type=party_type,
        party=party,
        text=text,
        channels=channels,
        kind=kind,
        sent_by=frappe.session.user,
    )


def _group_id():
    s = sender.settings()
    # deliver() sends to a group chat id only in Bot mode; User Account mode would log a false failure
    if not s.enabled or s.mode != "Bot":
        return ""
    return (s.get("group_chat_id") or "").strip()


def _group_sent_before(doctype, name, chat_id):
    return bool(frappe.db.exists("Hub Message Log", {
        "reference_doctype": doctype, "reference_name": name,
        "chat_id": chat_id, "status": "Sent", "party_type": ["is", "not set"],
    }))


def _party_phone(party_type, party):
    """Driver: Driver.cell_number -> Employee.cell_number -> User.mobile_no.
    User: User.mobile_no -> Employee.cell_number of the Employee linked to that user."""
    if party_type == DRIVER_DOCTYPE:
        d = frappe.db.get_value(DRIVER_DOCTYPE, party, ["cell_number", "employee", "user"], as_dict=True) or {}
        cell = d.get("cell_number")
        if not cell and d.get("employee") and frappe.db.exists("Employee", d.employee):
            cell = frappe.db.get_value("Employee", d.employee, "cell_number")
        if not cell and d.get("user") and frappe.db.exists("User", d.user):
            cell = frappe.db.get_value("User", d.user, "mobile_no")
    else:
        cell = frappe.db.get_value("User", party, "mobile_no")
        if not cell:
            cell = frappe.db.get_value("Employee", {"user_id": party}, "cell_number")
    return sender.normalize_phone(cell, sender.settings().default_country_code)


def send_to_party(doctype, name, party_type, party, text, channels, kind="Details", sent_by=None):
    if party_type == GROUP:
        return send_to_group(doctype, name, party, text, kind, sent_by)
    phone = _party_phone(party_type, party)
    for ch in channels:
        log = frappe.get_doc({
            "doctype": "Hub Message Log",
            "status": "Queued",
            "channel": ch,
            "reference_doctype": doctype,
            "reference_name": name,
            "party_type": party_type,
            "party": party,
            "mobile_no": phone,
            "message": text,
            "attach_print": 0,
        }).insert(ignore_permissions=True)
        frappe.db.commit()
        sender.deliver(log.name, notify=False)
        status, error = frappe.db.get_value("Hub Message Log", log.name, ["status", "error"])
        _log_activity(doctype, name, party_type, party, phone, ch, kind, status, error, text, sent_by)


def send_to_group(doctype, name, chat_id, text, kind="Details", sent_by=None):
    log = frappe.get_doc({
        "doctype": "Hub Message Log",
        "status": "Queued",
        "channel": "Telegram",
        "reference_doctype": doctype,
        "reference_name": name,
        "chat_id": chat_id,
        "message": text,
        "attach_print": 0,
    }).insert(ignore_permissions=True)
    frappe.db.commit()
    sender.deliver(log.name, notify=False)
    status, error = frappe.db.get_value("Hub Message Log", log.name, ["status", "error"])
    _log_group_activity(doctype, name, chat_id, kind, status, error, text, sent_by)


def _log_group_activity(doctype, name, chat_id, kind, status, error, text, sent_by):
    try:
        sender_name = frappe.db.get_value("User", sent_by, "full_name") or sent_by or "System"
        icon = {"Sent": "✅"}.get(status, "❌")
        head = f"{icon} <b>{escape_html(kind)}</b> sent to Telegram group <b>{escape_html(chat_id)}</b> " \
               f"via <b>Telegram</b>: <b>{escape_html(status or '-')}</b><br>" \
               f"By: {escape_html(sender_name)}"
        if error:
            head += f"<br>Reason: {escape_html(error).replace(chr(10), '<br>')}"
        body = escape_html(text).replace("\n", "<br>")
        frappe.get_doc(doctype, name).add_comment("Info", f"{head}<br><br>{body}")
    except Exception:
        frappe.log_error(title="Telegram: group notification activity", message=frappe.get_traceback())


def _log_activity(doctype, name, party_type, party, phone, channel, kind, status, error, text, sent_by):
    """Write a line in the document's activity timeline: what was sent, to whom, by whom."""
    try:
        party_name = frappe.db.get_value(party_type, party, "full_name") or party
        sender_name = frappe.db.get_value("User", sent_by, "full_name") or sent_by or "System"
        to = f"{party_name} ({party})" + (f", {phone}" if phone else "")
        icon = {"Sent": "✅", "Not Linked": "⚠️"}.get(status, "❌")
        head = f"{icon} <b>{escape_html(kind)}</b> sent to {escape_html(party_type)} <b>{escape_html(to)}</b> " \
               f"via <b>{channel}</b>: <b>{escape_html(status or '-')}</b><br>" \
               f"By: {escape_html(sender_name)}"
        if error:
            head += f"<br>Reason: {escape_html(error).replace(chr(10), '<br>')}"
        body = escape_html(text).replace("\n", "<br>")
        frappe.get_doc(doctype, name).add_comment("Info", f"{head}<br><br>{body}")
    except Exception:
        frappe.log_error(title="Telegram: driver notification activity", message=frappe.get_traceback())


def _sent_before(doctype, name, party_type, party):
    return bool(frappe.db.exists("Hub Message Log", {
        "reference_doctype": doctype, "reference_name": name,
        "party_type": party_type, "party": party, "status": "Sent",
    }))


# ---------------- Messages ----------------
def _fmt(doctype, fieldname, value):
    if value in (None, ""):
        return "-"
    df = frappe.get_meta(doctype).get_field(fieldname)
    return frappe.format_value(value, df=df) if df else str(value)


def _stop_label(row):
    parts = [row.get("customer_name") or row.get("customer") or "Stop"]
    if row.get("address"):
        parts.append(row.address)
    if row.get("delivery_note"):
        parts.append(f"DN: {row.delivery_note}")
    return " - ".join(parts)


def full_message(doc, title):
    cfg = DOCTYPE_CONFIG[doc.doctype]
    meta = frappe.get_meta(doc.doctype)
    lines = [title, f"{doc.doctype}: {doc.name}"]
    for f in cfg["fields"]:
        if not meta.has_field(f):
            continue
        value = doc.get(f)
        if f == "customer":
            value = doc.get("customer_name") or value
        if value in (None, ""):
            continue
        lines.append(f"{meta.get_label(f)}: {_fmt(doc.doctype, f, doc.get(f)) if f != 'customer' else value}")
    if cfg["stops"]:
        stops = doc.get("delivery_stops") or []
        if stops:
            lines.append("")
            lines.append("Stops:")
            for i, row in enumerate(stops, 1):
                lines.append(f"{i}. {_stop_label(row)}")
        else:
            lines.append("No stops yet.")
    return "\n".join(lines)


def update_message(doc, changes):
    head = [f"{doc.doctype} {doc.name} was updated:"]
    body = [f"- {c}" for c in changes]
    return "\n".join(head + body + ["", full_message(doc, "Current details")])


def reassigned_message(doc):
    return (
        f"{doc.doctype} {doc.name} has been reassigned to another driver.\n"
        "You are no longer assigned to this one."
    )


def describe_changes(doc, before):
    cfg = DOCTYPE_CONFIG[doc.doctype]
    meta = frappe.get_meta(doc.doctype)
    changes = []
    for f in cfg["fields"]:
        if not meta.has_field(f):
            continue
        old, new = before.get(f), doc.get(f)
        if _norm(old) != _norm(new):
            changes.append(f"{meta.get_label(f)}: {_fmt(doc.doctype, f, old)} -> {_fmt(doc.doctype, f, new)}")

    if cfg["stops"]:
        child_meta = frappe.get_meta(STOP_DOCTYPE)
        old_rows = {r.name: r for r in before.get("delivery_stops") or []}
        new_rows = {r.name: r for r in doc.get("delivery_stops") or []}
        for name, row in new_rows.items():
            if name not in old_rows:
                changes.append(f"Stop added: {_stop_label(row)}")
                continue
            old_row = old_rows[name]
            for f in STOP_FIELDS:
                if not child_meta.has_field(f):
                    continue
                if _norm(old_row.get(f)) != _norm(row.get(f)):
                    changes.append(
                        f"Stop {_stop_label(old_row)}: {child_meta.get_label(f)} "
                        f"{_fmt(STOP_DOCTYPE, f, old_row.get(f))} -> {_fmt(STOP_DOCTYPE, f, row.get(f))}"
                    )
        for name, row in old_rows.items():
            if name not in new_rows:
                changes.append(f"Stop removed: {_stop_label(row)}")
    return changes


def _norm(value):
    return "" if value is None else str(value)
    