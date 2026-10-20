"""Send one Telegram text to ERPNext users, by the mobile number on their User.

Shared by the Transportation Request / Delivery Trip messages. Every send is logged in Hub
Message Log and written to the document's Activity timeline (what, to whom, by whom). Delivery
uses the Notification Hub settings: User Account mode sends to the phone number; Bot mode needs
the user to have linked their Telegram first.
"""

import frappe
from frappe.utils import escape_html, get_url

from telegram_connector import sender

CHANNEL = "Telegram"
DASHBOARD_PATH = "/assets/logistics_hub/supervisor_dashboard.html"
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def site_url():
	"""Address of this installation, on whatever domain it is deployed.

	1. The domain of the current request - the address the users really open it on (behind a reverse
	   proxy: X-Forwarded-Host / X-Forwarded-Proto). Loopback addresses are skipped.
	2. Otherwise Frappe's own address: the site's ``host_name`` config, or the site name.
	"""
	request = getattr(frappe.local, "request", None)
	if request:
		host = (frappe.get_request_header("X-Forwarded-Host") or request.host or "").split(",")[0].strip()
		if host and host.split(":")[0].strip("[]") not in LOCAL_HOSTS:
			proto = (frappe.get_request_header("X-Forwarded-Proto") or request.scheme or "http").split(",")[0].strip()
			return f"{proto}://{host}"
	return get_url().rstrip("/")


def dashboard_link(query, base_url=None):
	"""Supervisor dashboard link, e.g. dashboard_link("tab=trips&trip=MAT-DT-...")."""
	return f"{(base_url or site_url()).rstrip('/')}{DASHBOARD_PATH}?{query}"


def users_with_role(role):
	users = set(frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent"))
	users.discard("Administrator")
	return sorted(u for u in users if frappe.db.get_value("User", u, "enabled"))


def send_to_users(doc, users, text, kind, sent_by=None):
	"""Send ``text`` to each user (log + activity line on ``doc``)."""
	cc = sender.settings().default_country_code
	for user in users:
		mobile = frappe.db.get_value("User", user, "mobile_no") or frappe.db.get_value("User", user, "phone")
		# Any country: the user's own country (time zone) is tried first for a local number.
		phone = sender.normalize_phone(mobile, cc, regions=[sender.region_for_user(user)])
		log = frappe.get_doc({
			"doctype": "Hub Message Log",
			"status": "Queued",
			"channel": CHANNEL,
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"party_type": "User",
			"party": user,
			"mobile_no": phone,
			"message": text,
			"attach_print": 0,
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		sender.deliver(log.name, notify=False)
		status, error = frappe.db.get_value("Hub Message Log", log.name, ["status", "error"])
		log_activity(doc, kind, user, phone, status, error, text, sent_by)


def log_activity(doc, kind, user, phone, status, error, text, sent_by):
	"""Line in the document's Activity timeline: what was sent, to whom, by whom."""
	try:
		user_name = frappe.db.get_value("User", user, "full_name") or user
		sender_name = frappe.db.get_value("User", sent_by, "full_name") or sent_by or "System"
		to = f"{user_name} ({user})" + (f", {phone}" if phone else "")
		icon = {"Sent": "✅", "Not Linked": "⚠️"}.get(status, "❌")
		head = (
			f"{icon} <b>{escape_html(kind)}</b> sent to <b>{escape_html(to)}</b> via <b>{CHANNEL}</b>: "
			f"<b>{escape_html(status or '-')}</b><br>By: {escape_html(sender_name)}"
		)
		if error:
			head += f"<br>Reason: {escape_html(error).replace(chr(10), '<br>')}"
		doc.add_comment("Info", f"{head}<br><br>{escape_html(text).replace(chr(10), '<br>')}")
	except Exception:
		frappe.log_error(title=f"Telegram: {kind} activity", message=frappe.get_traceback())
