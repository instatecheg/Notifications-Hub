import frappe

from telegram_connector.presets import PRESETS

DEFAULT_MESSAGE = PRESETS["Sales Invoice"]["message"]


def after_install():
    if not frappe.db.exists("DocType", "Sales Invoice"):
        return
    hub = frappe.get_single("Notification Hub")
    if any(r.document_type == "Sales Invoice" for r in hub.notifications):
        return
    hub.append("notifications", {
        "title": "Sales Invoice - Submit",
        "enabled": 1,
        "document_type": "Sales Invoice",
        "event": "Submit",
        "channel": "Telegram",
        "send_to_contact": 1,
        "mobile_field": "contact_mobile",
        "party_field": "customer",
        "party_doctype": "Customer",
        "party_mobile_field": "mobile_no",
        "prefer_party_mobile": 1,
        "message": DEFAULT_MESSAGE,
    })
    hub.save(ignore_permissions=True)
