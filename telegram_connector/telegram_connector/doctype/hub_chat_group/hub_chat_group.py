import re

import frappe
from frappe.model.document import Document


class HubChatGroup(Document):
    def validate(self):
        self.chat_id = (self.chat_id or "").strip()
        if self.channel == "WhatsApp" and not self.chat_id.endswith("@g.us"):
            frappe.throw("A WhatsApp group id ends with @g.us, e.g. 120363012345678901@g.us. "
                         "Click WhatsApp Diagnostics in Notification Hub to list your groups.")
        if self.channel == "Telegram" and not re.fullmatch(r"-\d+|@\w{4,}", self.chat_id):
            frappe.throw("A Telegram group chat id is a negative number, e.g. -1001234567890 "
                         "(or @channelname for a public channel).")
