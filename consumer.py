import pika
import os
import logging
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
ROUTING_KEY = "calendar.invite"
QUEUE_NAME = "planning.calendar.invite"

REQUIRED_HEADER_FIELDS = {"message_id", "timestamp", "source", "type"}
REQUIRED_BODY_FIELDS = {"session_id", "title", "start_datetime", "end_datetime"}


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
    missing_body = REQUIRED_BODY_FIELDS - body_tags
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
        "calendar.invite ontvangen | message_id=%s | source=%s | session_id=%s | title=%s | %s → %s | location=%s",
        message_id, source, session_id, title, start_datetime, end_datetime, location,
    )


def on_message(channel, method, properties, body: bytes):
    logger.info("Bericht ontvangen op routing key '%s'", method.routing_key)

    root = validate_xml(body)
    if root is None:
        logger.error(
            "Ongeldig bericht — wordt geweigerd (nack, no requeue)\nInhoud:\n%s",
            body.decode("utf-8", errors="replace"),
        )
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    handle_calendar_invite(root)
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
    channel.queue_bind(
        queue=QUEUE_NAME,
        exchange=EXCHANGE_NAME,
        routing_key=ROUTING_KEY,
    )

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=QUEUE_NAME, on_message_callback=on_message)

    logger.info(
        "Consumer gestart | exchange=%s | queue=%s | routing_key=%s | vhost=%s",
        EXCHANGE_NAME, QUEUE_NAME, ROUTING_KEY, RABBITMQ_VHOST,
    )
    channel.start_consuming()


if __name__ == "__main__":
    start_consumer()
