import frappe

INTERNAL = {"Notification Hub", "Hub Notification Rule", "Hub Message Log", "Telegram Link", "Hub Chat Group"}
EVENTS = {"after_insert": "New", "on_update": "Save", "on_submit": "Submit", "on_cancel": "Cancel"}
# Value Change is checked on every save, also on Update After Submit
VALUE_CHANGE_METHODS = {"on_update", "on_update_after_submit"}


def handle(doc, method=None):
    f = frappe.flags
    if f.in_import or f.in_patch or f.in_install or f.in_migrate:
        return
    if doc.doctype in INTERNAL:
        return
    event = EVENTS.get(method)
    if not event and method not in VALUE_CHANGE_METHODS:
        return
    if not (
        frappe.db.get_single_value("Notification Hub", "enabled")
        or frappe.db.get_single_value("Notification Hub", "whatsapp_enabled")
    ):
        return
    events = [event] if event else []
    if method in VALUE_CHANGE_METHODS:
        events.append("Value Change")
    rules = frappe.get_all(
        "Hub Notification Rule",
        filters={"enabled": 1, "document_type": doc.doctype, "event": ("in", events)},
        fields=["name", "event", "value_changed"],
    )
    for r in rules:
        extra = {"changed_by": frappe.session.user}
        if r.event == "Value Change":
            # a new document has no previous value to compare with
            before = doc.get_doc_before_save()
            if not before or not r.value_changed or not doc.has_value_changed(r.value_changed):
                continue
            df = doc.meta.get_field(r.value_changed)
            extra.update(
                field_label=df.label if df else r.value_changed,
                old_value=_fmt(before, r.value_changed, df),
                new_value=_fmt(doc, r.value_changed, df),
            )
        frappe.enqueue(
            "telegram_connector.sender.process_rule",
            queue="short",
            enqueue_after_commit=True,
            rule=r.name,
            ref_doctype=doc.doctype,
            ref_name=doc.name,
            extra=extra,
        )


def _fmt(doc, fieldname, df):
    v = doc.get(fieldname)
    if v in (None, ""):
        return "-"
    return frappe.format_value(v, df=df, doc=doc) if df else str(v)
