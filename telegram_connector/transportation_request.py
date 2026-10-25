"""Telegram message when a Transportation Request reaches "Documents requested".

One message is posted to the Telegram group (Notification Hub > Group Chat ID) where the
diesel / documents team that presses "Ready for start trip" is, with:
- a link that opens the request in the supervisor dashboard,
- Vehicle Internal Code, Driver Name, From and To.

Sending, logging and the Activity timeline line are shared (telegram_connector/driver_notifications.py).
"""

from urllib.parse import quote

import frappe

from telegram_connector import sender
from telegram_connector.driver_notifications import _group_id, send_to_group
from telegram_connector.user_messages import CHANNEL, dashboard_link, site_url

DOCTYPE = "Transportation Request"
STATE = "Documents requested"


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


def send_documents_request(name, sent_by=None, base_url=None):
	doc = frappe.get_doc(DOCTYPE, name)
	group_id = _group_id()
	if not group_id:
		# Nowhere to send to: say so on the request instead of failing silently.
		doc.add_comment(
			"Info",
			f"⚠️ <b>Documents request</b> not sent via <b>{CHANNEL}</b>: no Group Chat ID is set in "
			"Notification Hub.",
		)
		return
	send_to_group(DOCTYPE, name, group_id, message(doc, base_url), "Documents request", sent_by)


def _vehicle_internal_code(doc):
	"""The internal code shown on the dashboard (the assignment's Vehicle ID), else the assignment itself."""
	assignment = doc.get("vehicle_internal_code")
	if not assignment:
		return "-"
	if frappe.get_meta("Fleet Driver Assignment").has_field("lh_vehicle_id"):
		return frappe.db.get_value("Fleet Driver Assignment", assignment, "lh_vehicle_id") or assignment
	return assignment


def request_link(name, base_url=None):
	return dashboard_link(f"tab=requests&request={quote(name)}", base_url)


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
