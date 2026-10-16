"""Telegram message when a Transportation Request reaches "Documents requested".

Every enabled user with the "Document" role gets one message, sent to the mobile number on their
User (Mobile No, otherwise Phone), with:
- a link that opens the request in the supervisor dashboard,
- Vehicle Internal Code, Driver Name, From and To.

Each send is logged in Hub Message Log and in the request's Activity timeline. Delivery uses the
app's usual Telegram settings (Notification Hub): User Account mode sends to the phone number;
Bot mode needs the user to have linked their Telegram first.
"""

from urllib.parse import quote

import frappe
from frappe.utils import escape_html, get_url

from telegram_connector import sender

DOCTYPE = "Transportation Request"
STATE = "Documents requested"
ROLE = "Document"
CHANNEL = "Telegram"
DASHBOARD_PATH = "/assets/logistics_hub/supervisor_dashboard.html"


def on_update_after_submit(doc, method=None):
	f = frappe.flags
	if f.in_import or f.in_patch or f.in_install or f.in_migrate:
		return
	before = doc.get_doc_before_save()
	if doc.get("workflow_state") != STATE or (before and before.get("workflow_state") == STATE):
		return
	if not sender.channel_enabled(CHANNEL):
		return
	frappe.enqueue(
		"telegram_connector.transportation_request.send_documents_request",
		queue="short",
		enqueue_after_commit=True,
		name=doc.name,
		sent_by=frappe.session.user,
		# Taken now, while the request that triggered this is still here: the background job
		# has no request, so it could not tell which domain this installation is reached on.
		base_url=site_url(),
	)


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


def send_documents_request(name, sent_by=None, base_url=None):
	doc = frappe.get_doc(DOCTYPE, name)
	text = message(doc, base_url)
	cc = sender.settings().default_country_code
	for user in _document_users():
		mobile = frappe.db.get_value("User", user, "mobile_no") or frappe.db.get_value("User", user, "phone")
		# Any country: the user's own country (time zone) is tried first for a local number.
		phone = sender.normalize_phone(mobile, cc, regions=[sender.region_for_user(user)])
		log = frappe.get_doc({
			"doctype": "Hub Message Log",
			"status": "Queued",
			"channel": CHANNEL,
			"reference_doctype": DOCTYPE,
			"reference_name": name,
			"party_type": "User",
			"party": user,
			"mobile_no": phone,
			"message": text,
			"attach_print": 0,
		}).insert(ignore_permissions=True)
		frappe.db.commit()
		sender.deliver(log.name, notify=False)
		status, error = frappe.db.get_value("Hub Message Log", log.name, ["status", "error"])
		_log_activity(doc, user, phone, status, error, text, sent_by)


def _document_users():
	users = set(frappe.get_all("Has Role", filters={"role": ROLE, "parenttype": "User"}, pluck="parent"))
	users.discard("Administrator")
	return sorted(u for u in users if frappe.db.get_value("User", u, "enabled"))


def _vehicle_internal_code(doc):
	"""The internal code shown on the dashboard (the assignment's Vehicle ID), else the assignment itself."""
	assignment = doc.get("vehicle_internal_code")
	if not assignment:
		return "-"
	if frappe.get_meta("Fleet Driver Assignment").has_field("lh_vehicle_id"):
		return frappe.db.get_value("Fleet Driver Assignment", assignment, "lh_vehicle_id") or assignment
	return assignment


def request_link(name, base_url=None):
	return f"{(base_url or site_url()).rstrip('/')}{DASHBOARD_PATH}?tab=requests&request={quote(name)}"


def message(doc, base_url=None):
	return "\n".join([
		f"Documents requested for Transportation Request {doc.name}",
		f"Vehicle Internal Code: {_vehicle_internal_code(doc)}",
		f"Driver Name: {doc.get('driver_name') or doc.get('driver') or '-'}",
		f"From: {doc.get('from') or '-'}",
		f"To: {doc.get('to') or '-'}",
		"",
		f"Open the request: {request_link(doc.name, base_url)}",
	])


def _log_activity(doc, user, phone, status, error, text, sent_by):
	"""Line in the request's Activity timeline: what was sent, to whom, by whom."""
	try:
		user_name = frappe.db.get_value("User", user, "full_name") or user
		sender_name = frappe.db.get_value("User", sent_by, "full_name") or sent_by or "System"
		to = f"{user_name} ({user})" + (f", {phone}" if phone else "")
		icon = {"Sent": "✅", "Not Linked": "⚠️"}.get(status, "❌")
		head = (
			f"{icon} <b>Documents request</b> sent to <b>{escape_html(to)}</b> via <b>{CHANNEL}</b>: "
			f"<b>{escape_html(status or '-')}</b><br>By: {escape_html(sender_name)}"
		)
		if error:
			head += f"<br>Reason: {escape_html(error).replace(chr(10), '<br>')}"
		doc.add_comment("Info", f"{head}<br><br>{escape_html(text).replace(chr(10), '<br>')}")
	except Exception:
		frappe.log_error(title="Telegram: documents request activity", message=frappe.get_traceback())
