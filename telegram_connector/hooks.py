app_name = "telegram_connector"
app_title = "Telegram Connector"
app_publisher = "Shiftits"
app_description = "Send ERPNext notifications to customers via Telegram"
app_email = "erpnxtdeveloper678@gmail.com"
app_license = "MIT"
required_apps = ["frappe"]

after_install = "telegram_connector.install.after_install"
doctype_js = {
    # Telegram Link button (linking a customer's Telegram account) - kept
    "Customer": "public/js/customer.js",
    # Notify Customer button - switched off: only the Transportation Request message is sent now
    # "Sales Invoice": "public/js/sales_invoice.js",
}

# The only automatic message: a Transportation Request reaching "Documents requested" is sent on
# Telegram to every user with the "Document" role (telegram_connector/transportation_request.py).
#
# Switched off (code kept; uncomment to send them again):
# - Hub Notification Rules on every doctype:  "*": {"after_insert": _h, "on_update": _h, "on_submit": _h, "on_cancel": _h}
#   with _h = "telegram_connector.events.handle"
# - Details / changes to the assigned driver, the document's creator and the Telegram group
#   (Notification Hub > Group Chat ID): "Delivery Trip" and "Transportation Request"
#   {"on_update": _dt, "on_update_after_submit": _dt} with _dt = "telegram_connector.driver_notifications.on_update"
doc_events = {
    "Transportation Request": {
        "on_update_after_submit": "telegram_connector.transportation_request.on_update_after_submit",
    },
}

fixtures = [
    {"dt": "Role", "filters": [["name", "=", "Document"]]},
]

scheduler_events = {
    "cron": {"* * * * *": ["telegram_connector.sender.poll_updates"]},
    "daily": ["telegram_connector.sender.cleanup_public_pdfs"],
}
