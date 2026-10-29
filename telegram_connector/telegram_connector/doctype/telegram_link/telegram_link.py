import frappe
from frappe.model.document import Document
from frappe.utils import escape_html

from telegram_connector import sender


def result(title, message, indicator="green"):
    return {"title": title, "message": message, "indicator": indicator}


class TelegramLink(Document):
    def validate(self):
        cc = sender.settings().default_country_code
        if self.mobile_no:
            self.mobile_no = sender.normalize_phone(self.mobile_no, cc)
        if not (self.mobile_no or (self.party_type and self.party)):
            frappe.throw("Please select a party or enter a mobile number.", title="Recipient Required")
        if not self.token:
            self.token = frappe.generate_hash(length=10)
        self.deep_link = sender.make_deep_link(self.token)

    @frappe.whitelist()
    def link_now(self):
        if sender.settings().mode == "Bot":
            if not self.deep_link:
                frappe.throw("The bot username is not known yet. Please click Test Connection in the Telegram tab of Notification Hub first.",
                             title="Bot Username Missing")
            return result("Telegram Link", "Please send this link to the recipient. Once they open it and press Start, "
                          f"their account will be linked:<br><br><b>{escape_html(self.deep_link)}</b>", "blue")
        try:
            info = sender.resolve_user(self.mobile_no)
            self.db_set({"chat_id": str(info["id"]), "telegram_username": info["username"],
                         "status": "Linked", "last_error": ""})
            return result("Account Linked", "The Telegram account has been linked successfully.")
        except Exception as e:
            self.db_set({"status": "Failed", "last_error": str(e)})
            frappe.db.commit()
            return result("Linking Failed", escape_html(e).replace("\n", "<br>"), "red")

    @frappe.whitelist()
    def send_test(self):
        try:
            sender.send_text(self.chat_id, self.mobile_no, "This is a test message from ERPNext.")
            return result("Test Message Sent", "The test message was sent successfully.")
        except Exception as e:
            return result("Sending Failed", escape_html(e).replace("\n", "<br>"), "red")
