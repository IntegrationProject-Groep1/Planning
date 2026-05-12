import pika
import os
import logging
import threading
import json
import uuid
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from lxml import etree
from dotenv import load_dotenv
import producer
from xml_models import (
    CalendarInviteMessage,
    SessionCreatedMessage,
    SessionDeletedMessage,
    SessionCreateRequestMessage,
    SessionUpdateRequestMessage,
    SessionDeleteRequestMessage,
)
from graph_service import GraphService
from log_publisher import publish_log, publish_system_error, action_for_type
from calendar_service import MessageLog, SessionService, SessionRegistrationService, UserService, IcsFeedService

load_dotenv()

logging.basicConfig(level=logging.INFO)
logging.getLogger("pika").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

# Exchanges published by the sending teams; queues prefixed with our team name.
CALENDAR_EXCHANGE = os.getenv("CALENDAR_EXCHANGE", "calendar.exchange")
PLANNING_EXCHANGE = os.getenv("PLANNING_EXCHANGE", "planning.exchange")
ROUTING_KEY_VIEW_RESPONSE = "planning.to.frontend.session.view.response"
CALENDAR_ROUTING_KEYS = [
    key.strip()
    for key in os.getenv(
        "CALENDAR_ROUTING_KEYS",
        "frontend.to.planning.calendar.invite,crm.to.planning.cancel_registration",
    ).split(",")
    if key.strip()
]
SESSION_ROUTING_KEYS = [
    key.strip()
    for key in os.getenv(
        "SESSION_ROUTING_KEYS",
        (
            "frontend.to.planning.session.create,"
            "frontend.to.planning.session.update,"
            "frontend.to.planning.session.delete,"
            "frontend.to.planning.session.view,"
            "crm.to.planning.session_registration_confirmed,"
            "kassa.to.planning.user_sessions_request,"
            "frontend.to.planning.user_sessions_request"
        ),
    ).split(",")
    if key.strip()
]
CALENDAR_QUEUE_NAME = os.getenv("CALENDAR_QUEUE_NAME", "planning.calendar.invite")
SESSION_QUEUE_NAME = os.getenv("SESSION_QUEUE_NAME", "planning.session.events")

REQUIRED_HEADER_FIELDS = {"message_id", "timestamp", "source", "type"}
REQUIRED_BODY_FIELDS_BY_TYPE = {
    "calendar_invite": {"identity_uuid", "session_id", "title", "start_datetime", "end_datetime", "attendee_email"},
    "calendar.invite": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_created": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_updated": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_deleted": {"session_id"},
    "session_view_request": set(),
    "session_registration_confirmed": {"session_id"},
    "cancel_registration": {"session_id", "identity_uuid"},
    "session_create_request": {"title", "start_datetime", "end_datetime"},
    "session_update_request": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_delete_request": {"session_id"},
    "user_sessions_request": {"identity_uuid"},
}
_XSD_BY_TYPE = {
    "calendar_invite": "calendar_invite.xsd",
    "calendar.invite": "calendar_invite.xsd",
    "session_created": "session_created.xsd",
    "session_updated": "session_updated.xsd",
    "session_deleted": "session_deleted.xsd",
    "session_view_request": "session_view_request.xsd",
    "session_registration_confirmed": "session_registration_confirmed.xsd",
    "cancel_registration": "cancel_registration.xsd",
    "session_create_request": "session_create_request.xsd",
    "session_update_request": "session_update_request.xsd",
    "session_delete_request": "session_delete_request.xsd",
    "user_sessions_request": "user_sessions_request.xsd",
}

_SESSIONS: dict[str, dict[str, str | int]] = {}
_SESSIONS_LOCK = threading.Lock()

# Fields emitted per session in session_view_response XML (XSD allowlist).
# Order must match xs:sequence in session_view_response.xsd.
_XSD_SESSION_FIELDS = [
    "session_id", "title", "start_datetime", "end_datetime",
    "location", "session_type", "status", "max_attendees", "current_attendees",
]
# Fields that are xs:integer / xs:nonNegativeInteger — must not be emitted as "".
_XSD_INTEGER_FIELDS = {"max_attendees", "current_attendees"}




def _require_env(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _strip_ns(root: etree._Element) -> etree._Element:
    """Remove namespace prefixes from all element tags so find('header') works."""
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    return root


@lru_cache(maxsize=None)
def _load_schema(schema_filename: str) -> etree.XMLSchema:
    schema_path = Path(__file__).resolve().parent / "xsd" / schema_filename
    with schema_path.open("rb") as f:
        return etree.XMLSchema(etree.parse(f))


def validate_xml(body: bytes) -> etree._Element | None:
    """Parse and validate incoming XML. Returns root element or None on failure."""
    try:
        root_with_ns = etree.fromstring(body)
    except etree.XMLSyntaxError as e:
        logger.error("Malformed XML: %s", e)
        return None

    root = _strip_ns(etree.fromstring(body))

    message_type = root.findtext("header/type", default="")
    schema_filename = _XSD_BY_TYPE.get(message_type)
    if schema_filename is None:
        logger.error("Unsupported message type: %s", message_type)
        return None

    try:
        schema = _load_schema(schema_filename)
    except (OSError, etree.XMLSchemaParseError) as e:
        logger.error("Could not load/parse XSD schema '%s': %s", schema_filename, e)
        return None

    if not schema.validate(root):
        schema_error = schema.error_log.last_error
        logger.error(
            "XML failed XSD validation for type '%s': %s",
            message_type,
            schema_error,
        )
        return None

    header = root.find("header")
    message_body = root.find("body")

    if header is None or message_body is None:
        logger.error("Missing <header> or <body> element")
        return None

    header_tags = {child.tag for child in header}
    missing_header = REQUIRED_HEADER_FIELDS - header_tags
    if missing_header:
        logger.error("Missing required header fields: %s", missing_header)
        return None

    body_tags = {child.tag for child in message_body}
    required_body_fields = REQUIRED_BODY_FIELDS_BY_TYPE.get(message_type)

    missing_body = required_body_fields - body_tags
    if missing_body:
        logger.error("Missing required body fields: %s", missing_body)
        return None

    return root


def _body_to_session_payload(body: etree._Element) -> dict[str, str | int]:
    """Build a session payload from message body fields for read endpoints."""
    payload: dict[str, str | int] = {
        "session_id": body.findtext("session_id", default=""),
        "title": body.findtext("title", default=""),
        "start_datetime": body.findtext("start_datetime", default=""),
        "end_datetime": body.findtext("end_datetime", default=""),
        "location": body.findtext("location", default=""),
        "session_type": body.findtext("session_type", default=""),
        "status": body.findtext("status", default=""),
    }

    max_attendees = body.findtext("max_attendees")
    current_attendees = body.findtext("current_attendees")

    if max_attendees and max_attendees.isdigit():
        payload["max_attendees"] = int(max_attendees)
    if current_attendees and current_attendees.isdigit():
        payload["current_attendees"] = int(current_attendees)

    price_elem = body.find("price")
    if price_elem is not None and price_elem.text:
        try:
            payload["price"] = float(price_elem.text)
        except ValueError:
            pass

    return payload


def upsert_session(payload: dict[str, str | int]) -> None:
    session_id = str(payload.get("session_id", ""))
    if not session_id:
        return
    with _SESSIONS_LOCK:
        _SESSIONS[session_id] = payload


def delete_session(session_id: str) -> None:
    with _SESSIONS_LOCK:
        _SESSIONS.pop(session_id, None)


def list_sessions() -> list[dict[str, str | int]]:
    with _SESSIONS_LOCK:
        return [dict(v) for _, v in sorted(_SESSIONS.items())]


def get_session(session_id: str) -> dict[str, str | int] | None:
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(session_id)
        return dict(session) if session is not None else None


def _session_view_response_xml(
    request_header: etree._Element,
    requested_session_id: str | None,
    sessions: list[dict[str, str | int]],
    response_type: str = "session_view_response",
) -> str:
    """Build a session_view_response or session_view_response_all XML message."""
    root = etree.Element("message")

    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = response_type
    etree.SubElement(header, "version").text = "2.0"
    etree.SubElement(header, "correlation_id").text = (
        request_header.findtext("correlation_id")
        or request_header.findtext("message_id")
        or str(uuid.uuid4())
    )

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "request_message_id").text = request_header.findtext("message_id", default="")
    if requested_session_id:
        etree.SubElement(body, "requested_session_id").text = requested_session_id

    status = "ok" if sessions else "not_found"
    etree.SubElement(body, "status").text = status
    etree.SubElement(body, "session_count").text = str(len(sessions))

    sessions_elem = etree.SubElement(body, "sessions")
    for session in sessions:
        session_elem = etree.SubElement(sessions_elem, "session")
        for key in _XSD_SESSION_FIELDS:
            value = session.get(key)
            if value is None:
                value = 0 if key in _XSD_INTEGER_FIELDS else ""
            elif hasattr(value, "strftime"):
                value = value.strftime("%Y-%m-%dT%H:%M:%SZ")
            etree.SubElement(session_elem, key).text = str(value)
        if session.get("price") is not None:
            price_elem = etree.SubElement(session_elem, "price")
            price_elem.set("currency", "eur")
            price_elem.text = str(session["price"])

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def reset_sessions_store() -> None:
    """Clear session store (used by tests)."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()


# ── Inbound handlers ─────────────────────────────────────────────────────────

def handle_calendar_invite(msg: CalendarInviteMessage, channel, delivery_tag: int) -> None:
    """Process a validated calendar_invite message."""
    is_new = MessageLog.log_message(
        msg.header.message_id, "calendar_invite",
        source=msg.header.source, timestamp=msg.header.timestamp,
        correlation_id=msg.header.correlation_id,
    )
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        payload = {
            "session_id": msg.body.session_id,
            "title": msg.body.title,
            "start_datetime": msg.body.start_datetime,
            "end_datetime": msg.body.end_datetime,
            "location": msg.body.location or "",
        }
        SessionService.create_or_update(**payload)
        upsert_session(payload)

        ics_url = None
        if msg.body.master_uuid:
            SessionRegistrationService.register(
                session_id=msg.body.session_id,
                master_uuid=msg.body.master_uuid,
            )
            ics_feed = IcsFeedService.get_or_create(msg.body.master_uuid)
            if ics_feed and ics_feed.get("feed_token"):
                planning_url = os.getenv("PLANNING_SERVICE_URL", "http://localhost:30050")
                ics_url = f"{planning_url}/ics/{ics_feed['feed_token']}"
            GraphService.sync_created(
                session_id=msg.body.session_id,
                title=msg.body.title,
                start_datetime=msg.body.start_datetime,
                end_datetime=msg.body.end_datetime,
                location=msg.body.location or "",
                user_id=msg.body.master_uuid,
            )

        # §19.3: confirm calendar invite back to Frontend
        producer.publish_calendar_invite_confirmed(
            session_id=msg.body.session_id,
            original_message_id=msg.header.message_id,
            correlation_id=msg.header.correlation_id,
            ics_url=ics_url,
        )
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling calendar_invite: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_calendar_invite: {e}")
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_created(msg: SessionCreatedMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_created message."""
    is_new = MessageLog.log_message(
        msg.header.message_id, "session_created",
        source=msg.header.source, timestamp=msg.header.timestamp,
        correlation_id=msg.header.correlation_id,
    )
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        payload = {
            "session_id": msg.body.session_id,
            "title": msg.body.title,
            "start_datetime": msg.body.start_datetime,
            "end_datetime": msg.body.end_datetime,
            "location": msg.body.location or "",
            "session_type": msg.body.session_type or "keynote",
            "status": msg.body.status or "published",
            "max_attendees": msg.body.max_attendees or 0,
            "current_attendees": msg.body.current_attendees or 0,
        }
        SessionService.create_or_update(**payload)
        upsert_session(payload)
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_created: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_session_created: {e}")
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_updated(msg, channel, delivery_tag: int) -> None:
    """Process a validated session_updated message."""
    is_new = MessageLog.log_message(
        msg.header.message_id, "session_updated",
        source=msg.header.source, timestamp=msg.header.timestamp,
        correlation_id=msg.header.correlation_id,
    )
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        payload = {
            "session_id": msg.body.session_id,
            "title": msg.body.title,
            "start_datetime": msg.body.start_datetime,
            "end_datetime": msg.body.end_datetime,
            "location": msg.body.location or "",
            "session_type": msg.body.session_type or "keynote",
            "status": msg.body.status or "published",
            "max_attendees": msg.body.max_attendees or 0,
            "current_attendees": msg.body.current_attendees or 0,
        }
        SessionService.create_or_update(**payload)
        upsert_session(payload)
        GraphService.sync_updated(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
        )
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_updated: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_session_updated: {e}")
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_deleted(msg: SessionDeletedMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_deleted message."""
    is_new = MessageLog.log_message(
        msg.header.message_id, "session_deleted",
        source=msg.header.source, timestamp=msg.header.timestamp,
        correlation_id=msg.header.correlation_id,
    )
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        GraphService.sync_deleted(session_id=msg.body.session_id, reason=msg.body.reason or "Session cancelled")
        SessionService.delete(msg.body.session_id)
        delete_session(msg.body.session_id)
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_deleted: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_session_deleted: {e}")
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_view_request(root: etree._Element, channel) -> None:
    """Process a view request and publish view response to RabbitMQ."""
    header = root.find("header")
    body = root.find("body")
    requested_session_id = body.findtext("session_id", default="").strip()
    correlation_id = header.findtext("correlation_id") or header.findtext("message_id") or ""

    response_type = "session_view_response"

    if requested_session_id:
        session = SessionService.get(requested_session_id)
        sessions = [session] if session is not None else []
    else:
        sessions = SessionService.list_all(limit=200)

    response_xml = _session_view_response_xml(
        request_header=header,
        requested_session_id=requested_session_id or None,
        sessions=sessions,
        response_type=response_type
    )

    try:
        channel.basic_publish(
            exchange=PLANNING_EXCHANGE,
            routing_key=ROUTING_KEY_VIEW_RESPONSE,
            body=response_xml,
            properties=pika.BasicProperties(
                content_type="application/xml",
                delivery_mode=2,
            ),
        )
        # Log B — outbound message published
        publish_log(channel, "info", "session",
                    f"Published session_view_response to {ROUTING_KEY_VIEW_RESPONSE}. "
                    f"CorrelationID: {correlation_id}.")
        logger.info(
            "session_view_request processed | requested_session_id=%s | returned=%d | routing_key=%s",
            requested_session_id or "*",
            len(sessions),
            ROUTING_KEY_VIEW_RESPONSE,
        )
    except Exception as e:
        logger.error("Error publishing session_view_response: %s", e)
        # Log C — system failure
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_session_view_request: {e}")


def handle_session_registration_confirmed(root: etree._Element, channel) -> None:
    """Process a validated session_registration_confirmed message."""
    body = root.find("body")
    session_id = body.findtext("session_id") or ""

    if session_id:
        # §21.1: increment current_attendees then broadcast §21.2 occupancy update
        current, max_att = SessionService.increment_attendees(session_id)
        if current >= 0:
            producer.publish_session_occupancy_update(session_id, current, max_att)

    logger.info("session_registration_confirmed received | session_id=%s", session_id)


def handle_user_event(body: bytes, channel) -> None:
    """Handle UserCreated events from the user.events fanout (Identity Service).
    Flat XML format without <message><header> — read directly from <user_event>.
    """
    try:
        root = _strip_ns(etree.fromstring(body))
        event_type = root.findtext("event", default="")
        if event_type != "UserCreated":
            logger.info("user_event ignored | type=%s", event_type)
            return

        master_uuid = root.findtext("master_uuid", default="").strip()
        email = root.findtext("email", default="").strip()

        if not master_uuid or not email:
            logger.error("UserCreated event missing master_uuid or email")
            return

        UserService.save(master_uuid=master_uuid, email=email)
        logger.info("UserCreated processed | master_uuid=%s | email=%s", master_uuid, email)

    except etree.XMLSyntaxError as e:
        logger.error("Malformed XML in user_event: %s", e)
    except Exception as e:
        logger.error("Error in handle_user_event: %s", e)


def handle_cancel_registration(root: etree._Element, channel) -> None:
    """Process a validated cancel_registration message."""
    header = root.find("header")
    body = root.find("body")

    identity_uuid = body.findtext("identity_uuid") or ""
    session_id = body.findtext("session_id") or ""

    if session_id and identity_uuid:
        SessionRegistrationService.cancel(session_id=session_id, master_uuid=identity_uuid)
        # §21.2: decrement current_attendees then broadcast occupancy update
        current, max_att = SessionService.decrement_attendees(session_id)
        if current >= 0:
            producer.publish_session_occupancy_update(session_id, current, max_att)

    logger.info(
        "cancel_registration received | message_id=%s | identity_uuid=%s | session_id=%s",
        header.findtext("message_id"),
        identity_uuid,
        session_id,
    )


def handle_session_create_request(msg: SessionCreateRequestMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_create_request message."""
    is_new = MessageLog.log_message(
        msg.header.message_id, "session_create_request",
        source=msg.header.source, timestamp=msg.header.timestamp,
        correlation_id=msg.header.correlation_id,
    )
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        payload = {
            "session_id": msg.body.session_id,
            "title": msg.body.title,
            "start_datetime": msg.body.start_datetime,
            "end_datetime": msg.body.end_datetime,
            "location": msg.body.location or "",
            "session_type": msg.body.session_type or "keynote",
            "status": msg.body.status or "published",
            "max_attendees": msg.body.max_attendees or 0,
        }
        SessionService.create_or_update(**payload)
        upsert_session(payload)
        producer.publish_session_created(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            session_type=msg.body.session_type or "keynote",
            status=msg.body.status or "published",
            max_attendees=msg.body.max_attendees or 0,
            correlation_id=msg.header.correlation_id,
        )
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_create_request: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_session_create_request: {e}")
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_update_request(msg: SessionUpdateRequestMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_update_request message."""
    is_new = MessageLog.log_message(
        msg.header.message_id, "session_update_request",
        source=msg.header.source, timestamp=msg.header.timestamp,
        correlation_id=msg.header.correlation_id,
    )
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        payload = {
            "session_id": msg.body.session_id,
            "title": msg.body.title,
            "start_datetime": msg.body.start_datetime,
            "end_datetime": msg.body.end_datetime,
            "location": msg.body.location or "",
            "session_type": msg.body.session_type or "keynote",
            "status": msg.body.status or "published",
            "max_attendees": msg.body.max_attendees or 0,
            "current_attendees": msg.body.current_attendees or 0,
            "price": msg.body.price,
        }
        SessionService.create_or_update(**payload)
        upsert_session(payload)
        GraphService.sync_updated(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
        )
        producer.publish_session_updated(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            session_type=msg.body.session_type or "keynote",
            status=msg.body.status or "published",
            max_attendees=msg.body.max_attendees,
            current_attendees=msg.body.current_attendees,
            correlation_id=msg.header.correlation_id,
        )
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_update_request: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_session_update_request: {e}")
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_delete_request(msg: SessionDeleteRequestMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_delete_request message."""
    is_new = MessageLog.log_message(
        msg.header.message_id, "session_delete_request",
        source=msg.header.source, timestamp=msg.header.timestamp,
        correlation_id=msg.header.correlation_id,
    )
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        GraphService.sync_deleted(session_id=msg.body.session_id, reason=msg.body.reason or "Session deleted")
        SessionService.delete(msg.body.session_id)
        delete_session(msg.body.session_id)
        producer.publish_session_deleted(
            session_id=msg.body.session_id,
            reason=msg.body.reason,
            correlation_id=msg.header.correlation_id,
        )
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_delete_request: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_session_delete_request: {e}")
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_user_sessions_request(root: etree._Element, channel, properties) -> None:
    """Process a user_sessions_request (RPC) from Kassa or Frontend."""
    header = root.find("header")
    body = root.find("body")
    identity_uuid = body.findtext("identity_uuid", default="").strip()
    correlation_id = header.findtext("correlation_id", default="")
    reply_to = getattr(properties, "reply_to", None)

    sessions = IcsFeedService.get_user_sessions(identity_uuid)
    status = "ok" if sessions else "not_found"

    try:
        producer.publish_user_sessions_response(
            identity_uuid=identity_uuid,
            sessions=sessions,
            status=status,
            correlation_id=correlation_id,
            reply_to=reply_to,
        )
        logger.info(
            "user_sessions_request processed | identity_uuid=%s | sessions=%d | reply_to=%s",
            identity_uuid, len(sessions), reply_to,
        )
    except Exception as e:
        logger.error("Error publishing user_sessions_response: %s", e)
        publish_log(channel, "error", "system_error",
                    f"Internal Error in handle_user_sessions_request: {e}")


# ── Router ────────────────────────────────────────────────────────────────────

def route_message(msg, channel, delivery_tag: int) -> None:
    """Dispatch a typed message to the appropriate handler."""
    if isinstance(msg, CalendarInviteMessage):
        handle_calendar_invite(msg, channel, delivery_tag)
    elif isinstance(msg, SessionCreateRequestMessage):
        handle_session_create_request(msg, channel, delivery_tag)
    elif isinstance(msg, SessionUpdateRequestMessage):
        handle_session_update_request(msg, channel, delivery_tag)
    elif isinstance(msg, SessionDeleteRequestMessage):
        handle_session_delete_request(msg, channel, delivery_tag)
    elif isinstance(msg, SessionCreatedMessage):
        handle_session_created(msg, channel, delivery_tag)
    elif isinstance(msg, SessionDeletedMessage):
        handle_session_deleted(msg, channel, delivery_tag)
    else:
        logger.error("No handler for message type: %s", type(msg).__name__)
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


# ── Main message callback ─────────────────────────────────────────────────────

def on_message(channel, method, properties, body: bytes):
    logger.info("Message received on routing key '%s'", method.routing_key)

    # Extract type/source/message_id before full validation so we can log meaningful errors.
    try:
        _raw = _strip_ns(etree.fromstring(body))
        msg_type = _raw.findtext("header/type", default="unknown")
        msg_source = _raw.findtext("header/source", default="unknown")
        _related_message_id = _raw.findtext("header/message_id")
    except Exception:
        msg_type = "unknown"
        msg_source = "unknown"
        _related_message_id = None

    root = validate_xml(body)
    if root is None:
        # Log A — validation failure
        publish_log(channel, "error", "xml_validation",
                    f"Received {msg_type} from {msg_source}. Validation: Failure.")
        # §2.5.1: ACK (not NACK) to avoid queue blocking + system_error with invalid_xml_format
        publish_system_error(
            channel,
            error_code="invalid_xml_format",
            description=f"Incoming {msg_type} from {msg_source} failed XSD validation.",
            related_message_id=_related_message_id,
        )
        logger.error("Invalid message rejected | routing_key=%s", method.routing_key)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    # Log A — validation success
    publish_log(channel, "info", "xml_validation",
                f"Received {msg_type} from {msg_source}. Validation: Success.")

    message_type = root.find("header").findtext("type", default="")

    from xml_handlers import (
        parse_calendar_invite, parse_session_created, parse_session_updated,
        parse_session_deleted, parse_session_create_request,
        parse_session_update_request, parse_session_delete_request,
        parse_session_view_request, parse_user_sessions_request,
    )

    _type_parsers = {
        "calendar_invite":        parse_calendar_invite,
        "calendar.invite":        parse_calendar_invite,
        "session_created":        parse_session_created,
        "session_updated":        parse_session_updated,
        "session_deleted":        parse_session_deleted,
        "session_create_request": parse_session_create_request,
        "session_update_request": parse_session_update_request,
        "session_delete_request": parse_session_delete_request,
        "session_view_request":     parse_session_view_request,
        "user_sessions_request":    parse_user_sessions_request,
    }

    parser = _type_parsers.get(message_type)
    if parser is None:
        if message_type == "session_registration_confirmed":
            handle_session_registration_confirmed(root, channel)
            channel.basic_ack(delivery_tag=method.delivery_tag)
        elif message_type == "cancel_registration":
            handle_cancel_registration(root, channel)
            channel.basic_ack(delivery_tag=method.delivery_tag)
        else:
            logger.error("Unsupported message type after validation: %s", message_type)
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    if message_type == "session_view_request":
        msg = parser(body)
        if msg is None:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        handle_session_view_request(root, channel)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    if message_type == "user_sessions_request":
        msg = parser(body)
        if msg is None:
            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
            return
        handle_user_sessions_request(root, channel, properties)
        channel.basic_ack(delivery_tag=method.delivery_tag)
        return

    msg = parser(body)
    if msg is None:
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    route_message(msg, channel, method.delivery_tag)


def start_consumer():
    user = _require_env("RABBITMQ_USER", RABBITMQ_USER)
    password = _require_env("RABBITMQ_PASS", RABBITMQ_PASS)

    credentials = pika.PlainCredentials(user, password)
    params = pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=credentials,
        connection_attempts=3,
        retry_delay=2,
    )

    connection = pika.BlockingConnection(params)
    channel = connection.channel()

    channel.exchange_declare(
        exchange=CALENDAR_EXCHANGE,
        exchange_type="topic",
        durable=True,
    )
    channel.exchange_declare(
        exchange=PLANNING_EXCHANGE,
        exchange_type="topic",
        durable=True,
    )

    _dlx = os.getenv("PLANNING_DLX", "planning.dlx")
    _queue_args = {"x-dead-letter-exchange": _dlx}

    channel.queue_declare(queue=CALENDAR_QUEUE_NAME, durable=True, arguments=_queue_args)
    for routing_key in CALENDAR_ROUTING_KEYS:
        channel.queue_bind(
            queue=CALENDAR_QUEUE_NAME,
            exchange=CALENDAR_EXCHANGE,
            routing_key=routing_key,
        )

    channel.queue_declare(queue=SESSION_QUEUE_NAME, durable=True, arguments=_queue_args)
    for routing_key in SESSION_ROUTING_KEYS:
        channel.queue_bind(
            queue=SESSION_QUEUE_NAME,
            exchange=PLANNING_EXCHANGE,
            routing_key=routing_key,
        )

    # user.events fanout — Identity Service broadcast quand un user est créé
    USER_EVENTS_EXCHANGE = os.getenv("USER_EVENTS_EXCHANGE", "user.events")
    USER_EVENTS_QUEUE = os.getenv("USER_EVENTS_QUEUE", "planning.user.events")
    channel.exchange_declare(exchange=USER_EVENTS_EXCHANGE, exchange_type="fanout", durable=True)
    channel.queue_declare(queue=USER_EVENTS_QUEUE, durable=True)
    channel.queue_bind(queue=USER_EVENTS_QUEUE, exchange=USER_EVENTS_EXCHANGE)

    def on_user_event(ch, method, properties, body):
        handle_user_event(body, ch)
        ch.basic_ack(delivery_tag=method.delivery_tag)

    channel.basic_consume(queue=USER_EVENTS_QUEUE, on_message_callback=on_user_event)

    # Ensure infrastructure queues exist (durable, default exchange).
    channel.queue_declare(queue="logs", durable=True)
    channel.queue_declare(queue="planning.errors", durable=True)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=CALENDAR_QUEUE_NAME, on_message_callback=on_message)
    channel.basic_consume(queue=SESSION_QUEUE_NAME, on_message_callback=on_message)

    logger.info(
        "Consumer started | calendar_exchange=%s queue=%s keys=%s | planning_exchange=%s queue=%s keys=%s | vhost=%s",
        CALENDAR_EXCHANGE,
        CALENDAR_QUEUE_NAME,
        CALENDAR_ROUTING_KEYS,
        PLANNING_EXCHANGE,
        SESSION_QUEUE_NAME,
        SESSION_ROUTING_KEYS,
        RABBITMQ_VHOST,
    )
    channel.start_consuming()


def start_health_server(port: int = 30050):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status_code: int, payload: object):
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            if path in ("/", "/health"):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return

            if path == "/sessions":
                self._send_json(200, list_sessions())
                return

            if path.startswith("/sessions/"):
                session_id = path.split("/", 2)[2]
                session = get_session(session_id)
                if session is None:
                    self._send_json(404, {"error": "session_not_found", "session_id": session_id})
                    return
                self._send_json(200, session)
                return

            if path.startswith("/ics/"):
                from ics_service import build_ics
                from calendar_service import IcsFeedService
                feed_token = path.split("/", 2)[2]
                master_uuid = IcsFeedService.get_master_uuid_by_token(feed_token)
                if master_uuid is None:
                    self._send_json(404, {"error": "invalid_token"})
                    return
                sessions = IcsFeedService.get_user_sessions(master_uuid)
                ics_bytes = build_ics(sessions)
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=planning.ics")
                self.end_headers()
                self.wfile.write(ics_bytes)
                return

            self._send_json(404, {"error": "not_found", "path": path})

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"

            if path == "/api/tokens":
                # §19.0 — OAuth token registration (Frontend → Planning)
                auth = self.headers.get("Authorization", "")
                expected_token = os.getenv("API_TOKEN_SECRET", "")
                if not expected_token or auth != f"Bearer {expected_token}":
                    self._send_json(401, {"error": "unauthorized"})
                    return

                content_length = int(self.headers.get("Content-Length", 0))
                raw_body = self.rfile.read(content_length)
                try:
                    data = json.loads(raw_body)
                except (json.JSONDecodeError, ValueError):
                    self._send_json(400, {"error": "invalid_json"})
                    return

                identity_uuid = (data.get("identity_uuid") or "").strip()
                access_token = (data.get("access_token") or "").strip()
                refresh_token = (data.get("refresh_token") or "").strip()
                expires_in = int(data.get("expires_in") or 3600)

                if not identity_uuid or not access_token or not refresh_token:
                    self._send_json(400, {"error": "missing_required_fields"})
                    return

                try:
                    from token_service import TokenService
                    from datetime import timedelta
                    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                    TokenService.store(identity_uuid, access_token, refresh_token, expires_at)
                    self._send_json(200, {"status": "ok", "identity_uuid": identity_uuid})
                except Exception as exc:
                    logger.error("POST /api/tokens failed: %s", exc)
                    self._send_json(500, {"error": "internal_server_error"})
                return

            self._send_json(404, {"error": "not_found", "path": path})

        def log_message(self, format, *args):
            pass  # keep HTTP server requests out of service logs

    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health endpoint started on port %d", port)


if __name__ == "__main__":
    start_health_server()
    start_consumer()
