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
)
from graph_service import GraphService

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

# Exchanges published by the sending teams; queues prefixed with our team name.
CALENDAR_EXCHANGE = os.getenv("CALENDAR_EXCHANGE", "calendar.exchange")
PLANNING_EXCHANGE = os.getenv("PLANNING_EXCHANGE", "planning.exchange")
ROUTING_KEY_VIEW_RESPONSE = "planning.session.view.response"
CALENDAR_ROUTING_KEYS = [
    key.strip()
    for key in os.getenv(
        "CALENDAR_ROUTING_KEYS",
        "frontend.to.planning.calendar.invite",
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
            "crm.to.planning.cancel_registration,"
            "frontend.to.planning.cancel_registration"
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
}

_SESSIONS: dict[str, dict[str, str | int]] = {}
_SESSIONS_LOCK = threading.Lock()


class MessageLog:
    @staticmethod
    def log_message(message_id: str, message_type: str, source: str = "", **kwargs) -> bool:
        logger.debug("MessageLog.log_message: %s %s", message_type, message_id)
        return True

    @staticmethod
    def update_message_status(message_id: str, status: str, **kwargs) -> None:
        logger.debug("MessageLog.update_message_status: %s -> %s", message_id, status)


class SessionService:
    @staticmethod
    def create_or_update(session_id: str, **kwargs) -> bool:
        logger.debug("SessionService.create_or_update: %s", session_id)
        return True


class CalendarInviteService:
    @staticmethod
    def create(**kwargs) -> bool:
        logger.debug("CalendarInviteService.create")
        return True


class SessionEventService:
    @staticmethod
    def log_event(**kwargs) -> bool:
        logger.debug("SessionEventService.log_event")
        return True


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

    if not schema.validate(root_with_ns):
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
) -> str:
    """Build a session_view_response XML message."""
    root = etree.Element("message", xmlns="urn:integration:planning:v1")

    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = "session_view_response"
    etree.SubElement(header, "version").text = "1.0"
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
        for key, value in session.items():
            etree.SubElement(session_elem, key).text = str(value)

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def reset_sessions_store() -> None:
    """Clear session store (used by tests)."""
    with _SESSIONS_LOCK:
        _SESSIONS.clear()


def handle_calendar_invite(msg: CalendarInviteMessage, channel, delivery_tag: int) -> None:
    """Process a validated calendar.invite message."""
    is_new = MessageLog.log_message(msg.header.message_id, "calendar.invite", source=msg.header.source)
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location,
        )
        CalendarInviteService.create(
            message_id=msg.header.message_id,
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
        )
        GraphService.sync_created(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            user_id=msg.body.user_id,
        )
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling calendar.invite: %s", e)
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_created(msg: SessionCreatedMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_created message."""
    is_new = MessageLog.log_message(msg.header.message_id, "session_created", source=msg.header.source)
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
        )
        SessionEventService.log_event(session_id=msg.body.session_id, event_type="created")
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_created: %s", e)
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_updated(msg, channel, delivery_tag: int) -> None:
    """Process a validated session_updated message."""
    is_new = MessageLog.log_message(msg.header.message_id, "session_updated", source=msg.header.source)
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
        )
        SessionEventService.log_event(session_id=msg.body.session_id, event_type="updated")
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_updated: %s", e)
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_deleted(msg: SessionDeletedMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_deleted message."""
    is_new = MessageLog.log_message(msg.header.message_id, "session_deleted", source=msg.header.source)
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        delete_session(msg.body.session_id)
        MessageLog.update_message_status(msg.header.message_id, "processed")
        channel.basic_ack(delivery_tag=delivery_tag)
    except Exception as e:
        logger.error("Error handling session_deleted: %s", e)
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_view_request(root: etree._Element, channel) -> None:
    """Process a view request and publish view response to RabbitMQ."""
    header = root.find("header")
    body = root.find("body")
    requested_session_id = body.findtext("session_id", default="").strip()

    if requested_session_id:
        session = get_session(requested_session_id)
        sessions = [session] if session is not None else []
    else:
        sessions = list_sessions()

    response_xml = _session_view_response_xml(
        request_header=header,
        requested_session_id=requested_session_id or None,
        sessions=sessions,
    )

    channel.basic_publish(
        exchange=PLANNING_EXCHANGE,
        routing_key=ROUTING_KEY_VIEW_RESPONSE,
        body=response_xml,
        properties=pika.BasicProperties(
            content_type="application/xml",
            delivery_mode=2,
        ),
    )

    logger.info(
        "session_view_request processed | requested_session_id=%s | returned=%d | response_routing_key=%s",
        requested_session_id or "*",
        len(sessions),
        ROUTING_KEY_VIEW_RESPONSE,
    )


def handle_session_registration_confirmed(root: etree._Element):
    """Process a validated session_registration_confirmed message."""
    header = root.find("header")
    body = root.find("body")
    
    correlation_id = header.findtext("correlation_id")
    session_id = body.findtext("session_id")

    logger.info(
        "session_registration_confirmed received | correlation_id=%s | message_id=%s | session_id=%s",
        correlation_id,
        header.findtext("message_id"),
        session_id,
    )
    # Registration confirmed logic would go here (e.g., updating database)


def handle_cancel_registration(root: etree._Element):
    """Process a validated cancel_registration message."""
    header = root.find("header")
    body = root.find("body")
    
    identity_uuid = body.findtext("identity_uuid")
    session_id = body.findtext("session_id")

    logger.info(
        "cancel_registration received | message_id=%s | identity_uuid=%s | session_id=%s",
        header.findtext("message_id"),
        identity_uuid,
        session_id,
    )
    # Cancellation logic: find registration for identity_uuid/session_id and remove/deactivate


def handle_session_create_request(msg: SessionCreateRequestMessage, channel, delivery_tag: int) -> None:
    """Process a validated session_create_request message."""
    is_new = MessageLog.log_message(msg.header.message_id, "session_create_request", source=msg.header.source)
    if not is_new:
        channel.basic_ack(delivery_tag=delivery_tag)
        return
    try:
        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
        )
        SessionEventService.log_event(session_id=msg.body.session_id, event_type="create_request")
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
        MessageLog.update_message_status(msg.header.message_id, "failed")
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_update_request(root: etree._Element):
    """Process a validated session_update_request message."""
    header = root.find("header")
    body = root.find("body")
    
    logger.info(
        "session_update_request received | message_id=%s | session_id=%s | title=%s",
        header.findtext("message_id"),
        body.findtext("session_id"),
        body.findtext("title"),
    )
    # Logic to update a session


def handle_session_delete_request(root: etree._Element):
    """Process a validated session_delete_request message."""
    header = root.find("header")
    body = root.find("body")
    
    logger.info(
        "session_delete_request received | message_id=%s | session_id=%s | reason=%s",
        header.findtext("message_id"),
        body.findtext("session_id"),
        body.findtext("reason", default=""),
    )
    # Logic to delete a session


def route_message(msg, channel, delivery_tag: int) -> None:
    """Dispatch a typed message to the appropriate handler."""
    if isinstance(msg, CalendarInviteMessage):
        handle_calendar_invite(msg, channel, delivery_tag)
    elif isinstance(msg, SessionCreateRequestMessage):
        handle_session_create_request(msg, channel, delivery_tag)
    elif isinstance(msg, SessionCreatedMessage):
        handle_session_created(msg, channel, delivery_tag)
    elif isinstance(msg, SessionDeletedMessage):
        handle_session_deleted(msg, channel, delivery_tag)
    else:
        logger.error("No handler for message type: %s", type(msg).__name__)
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def on_message(channel, method, properties, body: bytes):
    logger.info("Message received on routing key '%s'", method.routing_key)

    root = validate_xml(body)
    if root is None:
        logger.error(
            "Invalid message - rejected (nack, no requeue)\nPayload:\n%s",
            body.decode("utf-8", errors="replace"),
        )
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    message_type = root.find("header").findtext("type", default="")

    from xml_handlers import (
        parse_calendar_invite, parse_session_created, parse_session_updated,
        parse_session_deleted, parse_session_create_request,
        parse_session_update_request, parse_session_delete_request,
        parse_session_view_request,
    )

    _type_parsers = {
        "calendar_invite": parse_calendar_invite,
        "calendar.invite": parse_calendar_invite,
        "session_created": parse_session_created,
        "session_updated": parse_session_updated,
        "session_deleted": parse_session_deleted,
        "session_create_request": parse_session_create_request,
        "session_update_request": parse_session_update_request,
        "session_delete_request": parse_session_delete_request,
        "session_view_request": parse_session_view_request,
    }

    parser = _type_parsers.get(message_type)
    if parser is None:
        if message_type in ("session_registration_confirmed", "cancel_registration"):
            handle_session_registration_confirmed(root) if message_type == "session_registration_confirmed" else handle_cancel_registration(root)
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

    channel.queue_declare(queue=CALENDAR_QUEUE_NAME, durable=True)
    for routing_key in CALENDAR_ROUTING_KEYS:
        channel.queue_bind(
            queue=CALENDAR_QUEUE_NAME,
            exchange=CALENDAR_EXCHANGE,
            routing_key=routing_key,
        )

    channel.queue_declare(queue=SESSION_QUEUE_NAME, durable=True)
    for routing_key in SESSION_ROUTING_KEYS:
        channel.queue_bind(
            queue=SESSION_QUEUE_NAME,
            exchange=PLANNING_EXCHANGE,
            routing_key=routing_key,
        )

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
