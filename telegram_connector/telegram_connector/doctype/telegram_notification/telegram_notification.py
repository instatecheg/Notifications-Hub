import frappe
from frappe.model.document import Document
from jinja2 import Environment, TemplateSyntaxError


class TelegramNotification(Document):
    def validate(self):
        try:
            Environment().parse(self.message or "")
        except TemplateSyntaxError as e:
            frappe.throw(f"Error in the message template: {e}")
