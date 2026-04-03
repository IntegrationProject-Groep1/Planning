import pika
import os
import logging
import threading
import json
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse
from lxml import etree
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

# Exchange published by the sending team; queue prefixed with our team name
EXCHANGE_NAME = os.getenv("CALENDAR_EXCHANGE", "calendar.exchange")
ROUTING_KEY_VIEW_RESPONSE = "planning.session.view.response"
ROUTING_KEYS = [
    key.strip()
    for key in os.getenv(
        "ROUTING_KEYS",
        "calendar.invite,planning.session.created,planning.session.updated,planning.session.deleted,planning.session.view.request",
    ).split(",")
    if key.strip()
]
QUEUE_NAME = "planning.calendar.invite"

REQUIRED_HEADER_FIELDS = {"message_id", "timestamp", "source", "type"}
REQUIRED_BODY_FIELDS_BY_TYPE = {
    "calendar.invite": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_created": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_updated": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_deleted": {"session_id"},
    "session_view_request": set(),
}

_SESSIONS: dict[str, dict[str, str | int]] = {}
_SESSIONS_LOCK = threading.Lock()


def _require_env(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _strip_ns(root: etree._Element) -> etree._Element:
    """Remove namespace prefixes from all element tags so find('header') works."""
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    return root


def validate_xml(body: bytes) -> etree._Element | None:
    """Parse and validate incoming XML. Returns root element or None on failure."""
    try:
        root = _strip_ns(etree.fromstring(body))
    except etree.XMLSyntaxError as e:
        logger.error("Malformed XML: %s", e)
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
    message_type = header.findtext("type", default="")
    required_body_fields = REQUIRED_BODY_FIELDS_BY_TYPE.get(message_type)
    if required_body_fields is None:
        logger.error("Unsupported message type: %s", message_type)
        return None

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


def handle_calendar_invite(root: etree._Element):
    """Process a validated calendar.invite message."""
    header = root.find("header")
    body = root.find("body")

    message_id = header.findtext("message_id")
    source = header.findtext("source")
    session_id = body.findtext("session_id")
    title = body.findtext("title")
    start_datetime = body.findtext("start_datetime")
    end_datetime = body.findtext("end_datetime")
    location = body.findtext("location", default="")

    logger.info(
        "calendar.invite received | message_id=%s | source=%s | session_id=%s | title=%s | %s -> %s | location=%s",
        message_id, source, session_id, title, start_datetime, end_datetime, location,
    )

    upsert_session(_body_to_session_payload(body))


def handle_session_created(root: etree._Element):
    """Process a validated session_created message."""
    header = root.find("header")
    body = root.find("body")

    logger.info(
        "session_created received | message_id=%s | source=%s | session_id=%s | title=%s | %s -> %s",
        header.findtext("message_id"),
        header.findtext("source"),
        body.findtext("session_id"),
        body.findtext("title"),
        body.findtext("start_datetime"),
        body.findtext("end_datetime"),
    )

    upsert_session(_body_to_session_payload(body))


def handle_session_updated(root: etree._Element):
    """Process a validated session_updated message."""
    header = root.find("header")
    body = root.find("body")

    logger.info(
        "session_updated received | message_id=%s | source=%s | session_id=%s | title=%s | %s -> %s",
        header.findtext("message_id"),
        header.findtext("source"),
        body.findtext("session_id"),
        body.findtext("title"),
        body.findtext("start_datetime"),
        body.findtext("end_datetime"),
    )

    upsert_session(_body_to_session_payload(body))


def handle_session_deleted(root: etree._Element):
    """Process a validated session_deleted message."""
    header = root.find("header")
    body = root.find("body")

    logger.info(
        "session_deleted received | message_id=%s | source=%s | session_id=%s | reason=%s | deleted_by=%s",
        header.findtext("message_id"),
        header.findtext("source"),
        body.findtext("session_id"),
        body.findtext("reason", default=""),
        body.findtext("deleted_by", default=""),
    )

    delete_session(body.findtext("session_id", default=""))


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
        exchange=EXCHANGE_NAME,
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

    if message_type == "calendar.invite":
        handle_calendar_invite(root)
    elif message_type == "session_created":
        handle_session_created(root)
    elif message_type == "session_updated":
        handle_session_updated(root)
    elif message_type == "session_deleted":
        handle_session_deleted(root)
    elif message_type == "session_view_request":
        handle_session_view_request(root, channel)
    else:
        logger.error("Unsupported message type after validation: %s", message_type)
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    channel.basic_ack(delivery_tag=method.delivery_tag)


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
        exchange=EXCHANGE_NAME,
        exchange_type="topic",
        durable=True,
    )

    channel.queue_declare(queue=QUEUE_NAME, durable=True)
    for routing_key in ROUTING_KEYS:
        channel.queue_bind(
            queue=QUEUE_NAME,
            exchange=EXCHANGE_NAME,
            routing_key=routing_key,
        )

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)

    logger.info(
        "Consumer started | exchange=%s | queue=%s | routing_keys=%s | vhost=%s",
        EXCHANGE_NAME, QUEUE_NAME, ROUTING_KEYS, RABBITMQ_VHOST,
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
