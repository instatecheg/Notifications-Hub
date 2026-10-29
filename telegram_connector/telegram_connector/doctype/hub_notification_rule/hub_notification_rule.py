import frappe
from frappe.model.document import Document
from jinja2 import Environment, TemplateSyntaxError


class HubNotificationRule(Document):
    def before_insert(self):
        # Auto title so the user does not have to invent one
        if not self.title:
            base = f"{self.document_type} - {self.event} - {self.channel or 'Telegram'}"
            title, n = base, 1
            while frappe.db.exists("Hub Notification Rule", title):
                n += 1
                title = f"{base} ({n})"
            self.title = title

    def validate(self):
        try:
            Environment().parse(self.message or "")
        except TemplateSyntaxError as e:
            frappe.throw(f"Error in message template: {e}")
        self.validate_fields()

    def validate_fields(self):
        meta = frappe.get_meta(self.document_type)
        std = {"name", "owner", "modified_by", "docstatus", "creation", "modified"}

        def check(fieldname, where):
            if fieldname and fieldname not in std and not meta.has_field(fieldname):
                frappe.throw(f"{where}: {self.document_type} has no field '{fieldname}'")

        if self.event == "Value Change":
            check(self.value_changed, "Value Changed")
        if self.event in ("Days Before", "Days After"):
            check(self.date_changed, "Reference Date")
            df = meta.get_field(self.date_changed)
            if df and df.fieldtype not in ("Date", "Datetime"):
                frappe.throw(f"Reference Date: '{self.date_changed}' is not a date field")
            if (self.days_in_advance or 0) < 0:
                frappe.throw("Days cannot be negative")
        for c in self.conditions:
            check(c.fieldname, f"Conditions row {c.idx}")
            if c.operator not in ("is set", "is not set", "=", "!=") and not (c.value or "").strip():
                frappe.throw(f"Conditions row {c.idx}: enter a Value")
        for r in self.recipients:
            if r.recipient_type == "Document Field":
                check(r.document_field, f"Also Send To row {r.idx}")
        if not (self.send_to_document_contact or self.recipients or self.groups):
            frappe.throw("Choose at least one recipient: the document's customer / contact, Also Send To, or Groups")
