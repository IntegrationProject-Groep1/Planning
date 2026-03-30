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

# Exchange and routing key (with planning prefix per new infra standard)
EXCHANGE_NAME = 'planning.exchange'
ROUTING_KEY = 'planning.session.created'
XMLNS = "urn:integration:planning:v1"


def _require_env(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def create_session_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str,
    max_attendees: int = 120,
    current_attendees: int = 0
) -> str:
    """Create a session.created XML message with required header/body fields."""
    root = etree.Element("message", xmlns=XMLNS)

    header = etree.SubElement(root, "header")

    message_id_elem = etree.SubElement(header, "message_id")
    message_id_elem.text = str(uuid.uuid4())

    timestamp_elem = etree.SubElement(header, "timestamp")
    timestamp_elem.text = datetime.now(timezone.utc).isoformat()

    source_elem = etree.SubElement(header, "source")
    source_elem.text = "planning"

    type_elem = etree.SubElement(header, "type")
    type_elem.text = "session_created"

    version_elem = etree.SubElement(header, "version")
    version_elem.text = "1.0"

    correlation_id_elem = etree.SubElement(header, "correlation_id")
    correlation_id_elem.text = str(uuid.uuid4())

    body = etree.SubElement(root, "body")

    session_id_elem = etree.SubElement(body, "session_id")
    session_id_elem.text = session_id

    title_elem = etree.SubElement(body, "title")
    title_elem.text = title

    start_elem = etree.SubElement(body, "start_datetime")
    start_elem.text = start_datetime

    end_elem = etree.SubElement(body, "end_datetime")
    end_elem.text = end_datetime

    location_elem = etree.SubElement(body, "location")
    location_elem.text = location

    type_session_elem = etree.SubElement(body, "session_type")
    type_session_elem.text = "keynote"

    status_elem = etree.SubElement(body, "status")
    status_elem.text = "published"

    max_attendees_elem = etree.SubElement(body, "max_attendees")
    max_attendees_elem.text = str(max_attendees)

    current_attendees_elem = etree.SubElement(body, "current_attendees")
    current_attendees_elem.text = str(current_attendees)

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def validate_xml(xml_string: str) -> bool:
    try:
        etree.fromstring(xml_string.encode('utf-8'))
        return True
    except etree.XMLSyntaxError as e:
        logger.error(f"Invalid XML: {e}")
        return False


def send_message(xml_message: str):
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
            routing_key=ROUTING_KEY,
            body=xml_message,
            properties=pika.BasicProperties(
                content_type="application/xml",
                delivery_mode=2
            )
        )

        logger.info(f"Message sent with routing key '{ROUTING_KEY}'")
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

    success = send_message(session_xml)

    if success:
        logger.info("✓ Message successfully sent to RabbitMQ")
    else:
        logger.error("✗ Failed to send message to RabbitMQ")


if __name__ == "__main__":
    main()