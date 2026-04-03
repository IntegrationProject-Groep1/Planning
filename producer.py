import pika
import os
import logging
import uuid
from datetime import datetime, timezone
from lxml import etree
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# RabbitMQ connection settings
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")

# Exchange and routing keys (with planning prefix per new infra standard)
EXCHANGE_NAME = 'planning.exchange'
ROUTING_KEY = 'planning.session.created'
ROUTING_KEY_UPDATED = 'planning.session.updated'
ROUTING_KEY_DELETED = 'planning.session.deleted'
XMLNS = "urn:integration:planning:v1"


def _require_env(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _build_header(root: etree._Element, message_type: str) -> None:
    """Append a standard planning message header to *root*."""
    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = message_type
    etree.SubElement(header, "version").text = "1.0"
    etree.SubElement(header, "correlation_id").text = str(uuid.uuid4())


def create_session_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str,
    max_attendees: int = 120,
    current_attendees: int = 0,
    session_type: str = "keynote",
    status: str = "published",
) -> str:
    """Create a session.created XML message with required header/body fields."""
    root = etree.Element("message", xmlns=XMLNS)
    _build_header(root, "session_created")

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "session_id").text = session_id
    etree.SubElement(body, "title").text = title
    etree.SubElement(body, "start_datetime").text = start_datetime
    etree.SubElement(body, "end_datetime").text = end_datetime
    etree.SubElement(body, "location").text = location
    etree.SubElement(body, "session_type").text = session_type
    etree.SubElement(body, "status").text = status
    etree.SubElement(body, "max_attendees").text = str(max_attendees)
    etree.SubElement(body, "current_attendees").text = str(current_attendees)

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def create_session_update_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str,
    max_attendees: int = 120,
    current_attendees: int = 0,
    session_type: str = "keynote",
    status: str = "published",
) -> str:
    """Create a session.updated XML message with required header/body fields."""
    root = etree.Element("message", xmlns=XMLNS)
    _build_header(root, "session_updated")

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "session_id").text = session_id
    etree.SubElement(body, "title").text = title
    etree.SubElement(body, "start_datetime").text = start_datetime
    etree.SubElement(body, "end_datetime").text = end_datetime
    etree.SubElement(body, "location").text = location
    etree.SubElement(body, "session_type").text = session_type
    etree.SubElement(body, "status").text = status
    etree.SubElement(body, "max_attendees").text = str(max_attendees)
    etree.SubElement(body, "current_attendees").text = str(current_attendees)

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def create_session_delete_xml(session_id: str) -> str:
    """Create a session.deleted XML message with required header/body fields."""
    root = etree.Element("message", xmlns=XMLNS)
    _build_header(root, "session_deleted")

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "session_id").text = session_id

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def validate_xml(xml_string: str) -> bool:
    try:
        etree.fromstring(xml_string.encode('utf-8'))
        return True
    except etree.XMLSyntaxError as e:
        logger.error(f"Invalid XML: {e}")
        return False


def send_message(xml_message: str, routing_key: str = ROUTING_KEY):
    try:
        user = _require_env("RABBITMQ_USER", RABBITMQ_USER)
        password = _require_env("RABBITMQ_PASS", RABBITMQ_PASS)

        credentials = pika.PlainCredentials(user, password)

        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            credentials=credentials,
            connection_attempts=3,
            retry_delay=2
        )

        connection = pika.BlockingConnection(params)
        channel = connection.channel()

        channel.exchange_declare(
            exchange=EXCHANGE_NAME,
            exchange_type='topic',
            durable=True
        )

        if not validate_xml(xml_message):
            logger.error("Cannot send invalid XML message\nInhoud:\n%s", xml_message)
            connection.close()
            return False

        channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=routing_key,
            body=xml_message,
            properties=pika.BasicProperties(
                content_type="application/xml",
                delivery_mode=2
            )
        )

        logger.info(f"Message sent with routing key '{routing_key}'")
        connection.close()
        return True

    except pika.exceptions.AMQPConnectionError as e:
        logger.error(f"Failed to connect to RabbitMQ: {e}")
        return False
    except ValueError as e:
        logger.error(
            "%s. Set RABBITMQ_USER and RABBITMQ_PASS in your environment or .env file.",
            e,
        )
        return False
    except Exception as e:
        logger.error("Error sending message: %s", e, exc_info=True)
        return False


def main():
    session_xml = create_session_xml(
        session_id="sess-uuid-001",
        title="Keynote: AI in de zorgsector",
        start_datetime="2026-05-15T14:00:00Z",
        end_datetime="2026-05-15T15:00:00Z",
        location="online",
        max_attendees=120
    )
    logger.info("Created XML message:")
    logger.info(session_xml)
    success = send_message(session_xml, ROUTING_KEY)
    if success:
        logger.info("✓ session.created sent to RabbitMQ")
    else:
        logger.error("✗ Failed to send session.created")

    update_xml = create_session_update_xml(
        session_id="sess-uuid-001",
        title="Keynote: AI in de zorgsector (updated)",
        start_datetime="2026-05-15T14:30:00Z",
        end_datetime="2026-05-15T15:30:00Z",
        location="online",
        max_attendees=150
    )
    logger.info("Update XML message:")
    logger.info(update_xml)
    success = send_message(update_xml, ROUTING_KEY_UPDATED)
    if success:
        logger.info("✓ session.updated sent to RabbitMQ")
    else:
        logger.error("✗ Failed to send session.updated")

    delete_xml = create_session_delete_xml(session_id="sess-uuid-001")
    logger.info("Delete XML message:")
    logger.info(delete_xml)
    success = send_message(delete_xml, ROUTING_KEY_DELETED)
    if success:
        logger.info("✓ session.deleted sent to RabbitMQ")
    else:
        logger.error("✗ Failed to send session.deleted")


if __name__ == "__main__":
    main()