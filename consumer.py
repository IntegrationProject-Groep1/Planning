import pika
import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
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
ROUTING_KEYS = [
    key.strip()
    for key in os.getenv(
        "ROUTING_KEYS",
        "calendar.invite,planning.session.updated,planning.session.deleted",
    ).split(",")
    if key.strip()
]
QUEUE_NAME = "planning.calendar.invite"

REQUIRED_HEADER_FIELDS = {"message_id", "timestamp", "source", "type"}
REQUIRED_BODY_FIELDS_BY_TYPE = {
    "calendar.invite": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_updated": {"session_id", "title", "start_datetime", "end_datetime"},
    "session_deleted": {"session_id"},
}


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
    elif message_type == "session_updated":
        handle_session_updated(root)
    elif message_type == "session_deleted":
        handle_session_deleted(root)
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
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            pass  # keep HTTP server requests out of service logs

    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health endpoint started on port %d", port)


if __name__ == "__main__":
    start_health_server()
    start_consumer()
