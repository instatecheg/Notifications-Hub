import frappe

# Old rule doctypes whose records become rows of Notification Hub > Notifications.
# "Telegram Notification" is the pre-rename name, recreated on some sites by an old JSON file.
OLD = ("Hub Notification Rule", "Telegram Notification")
FIELDS = ("enabled", "document_type", "event", "condition", "mobile_field", "party_field", "party_doctype",
          "party_mobile_field", "prefer_party_mobile", "message", "attach_print", "print_format")


def execute():
    hub = frappe.get_single("Notification Hub")
    titles = {r.title for r in hub.notifications}
    added = 0
    for dt in OLD:
        if not frappe.db.table_exists(dt):
            continue
        cols = set(frappe.db.get_table_columns(dt))
        for r in frappe.db.sql(f"select * from `tab{dt}` order by creation", as_dict=True):
            title = r.get("title") or r.name
            if title in titles:
                continue
            row = {f: r.get(f) for f in FIELDS if f in cols}
            row.update(title=title, channel=r.get("channel") or "Telegram", send_to_contact=1)
            if row.get("event") not in ("New", "Save", "Submit", "Cancel"):
                row["event"] = "Submit"
            hub.append("notifications", row)
            titles.add(title)
            added += 1
    if added:
        hub.flags.skip_rule_checks = True  # keep old rules even if one would fail today's checks
        hub.save(ignore_permissions=True)
        frappe.db.commit()
    print(f"Notification Hub: moved {added} rule(s) into Notifications")
