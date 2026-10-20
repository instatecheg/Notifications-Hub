"""Telegram messages about a Delivery Trip to the supervisor who created its Transportation Request.

- The driver ends the trip (status becomes "Ended"): the supervisor is asked to review it.
- The driver asks for the customer location: the supervisor is asked to add it to the trip.

The recipient is the creator of the trip's Transportation Request; a trip that was not created
from a request goes to the user who created the trip. If that is Administrator (no phone) or a
disabled user, every enabled user with the Supervisor role gets it.
"""

from urllib.parse import quote

import frappe

from telegram_connector import sender
from telegram_connector.user_messages import CHANNEL, dashboard_link, send_to_users, site_url, users_with_role

DOCTYPE = "Delivery Trip"
SUPERVISOR_ROLE = "Supervisor"
ENDED = "Ended"


def on_update(doc, method=None):
	"""Draft trip saved with status "Ended" (it was not before): tell the supervisor."""
	f = frappe.flags
	if f.in_import or f.in_patch or f.in_install or f.in_migrate:
		return
	before = doc.get_doc_before_save()
	if doc.get("status") != ENDED or (before and before.get("status") == ENDED):
		return
	_enqueue(doc.name, "trip_ended")


def request_customer_location(trip):
	"""Driver app: ask the supervisor for the customer location of this trip."""
	_enqueue(trip, "customer_location")


def _enqueue(trip, kind):
	if not sender.channel_enabled(CHANNEL):
		return
	frappe.enqueue(
		"telegram_connector.delivery_trip.send",
		queue="short",
		enqueue_after_commit=True,
		trip=trip,
		kind=kind,
		sent_by=frappe.session.user,
		# Taken while the triggering request is here (the job has no request to read the domain from).
		base_url=site_url(),
	)


def send(trip, kind, sent_by=None, base_url=None):
	doc = frappe.get_doc(DOCTYPE, trip)
	if kind == "trip_ended":
		text, label = trip_ended_message(doc, base_url), "Trip ended"
	else:
		text, label = customer_location_message(doc, base_url), "Customer location request"
	recipients = supervisors_for(doc)
	if not recipients:
		# Nobody to send to: say so on the trip instead of failing silently.
		doc.add_comment(
			"Info",
			f"⚠️ <b>{label}</b> not sent via <b>{CHANNEL}</b>: the trip has no supervisor to send it to "
			f"(no request creator and no enabled user with the {SUPERVISOR_ROLE} role).",
		)
		return
	send_to_users(doc, recipients, text, label, sent_by)


def supervisors_for(doc):
	"""Creator of the trip's Transportation Request, else the trip's creator. When that is nobody
	usable (e.g. the trip was made by Administrator, who has no phone), every enabled Supervisor."""
	request = doc.get("lh_transportation_request") if doc.meta.has_field("lh_transportation_request") else None
	owner = frappe.db.get_value("Transportation Request", request, "owner") if request else None
	owner = owner or doc.owner
	if owner and owner != "Administrator" and frappe.db.get_value("User", owner, "enabled"):
		return [owner]
	return users_with_role(SUPERVISOR_ROLE)


def trip_link(name, base_url=None):
	return dashboard_link(f"tab=trips&trip={quote(name)}", base_url)


def _details(doc):
	return [
		f"Request: {doc.get('lh_transportation_request') or '-'}",
		f"Driver Name: {doc.get('driver_name') or doc.get('driver') or '-'}",
		f"Vehicle Internal Code: {doc.get('lh_vehicle_id') or doc.get('vehicle') or '-'}",
		f"From: {doc.get('lh_source_city') or '-'}",
		f"To: {doc.get('lh_destination_city') or '-'}",
	]


def trip_ended_message(doc, base_url=None):
	return "\n".join([
		f"Trip {doc.name} was ended by the driver and is waiting for your review.",
		*_details(doc),
		"",
		f"Review the trip: {trip_link(doc.name, base_url)}",
	])


def customer_location_message(doc, base_url=None):
	return "\n".join([
		f"The driver of trip {doc.name} asks for the customer location.",
		*_details(doc),
		"",
		f"Add the Customer Location to the trip: {trip_link(doc.name, base_url)}",
	])
