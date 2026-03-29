import pika
import os
import logging
import uuid
from datetime import datetime
from lxml import etree
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# RabbitMQ connection settings
RABBITMQ_USER = os.getenv('RABBITMQ_USER')
RABBITMQ_PASS = os.getenv('RABBITMQ_PASS')
RABBITMQ_HOST = os.getenv('RABBITMQ_HOST')
RABBITMQ_PORT = int(os.getenv('RABBITMQ_PORT', 5672))

# Exchange and routing key (with planning prefix per new infra standard)
EXCHANGE_NAME = 'planning.exchange'
ROUTING_KEY = 'planning.session.created'
XMLNS = "urn:integration:planning:v1"


def create_session_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str,
    speaker_name: str,
    speaker_company: str,
    session_type: str = "keynote",
    max_attendees: int = 120
) -> str:
    root = etree.Element('message', xmlns=XMLNS)

    header = etree.SubElement(root, 'header')

    message_id_elem = etree.SubElement(header, 'message_id')
    message_id_elem.text = str(uuid.uuid4())

    timestamp_elem = etree.SubElement(header, 'timestamp')
    timestamp_elem.text = datetime.utcnow().isoformat() + "Z"

    source_elem = etree.SubElement(header, 'source')
    source_elem.text = 'planning'

    type_elem = etree.SubElement(header, 'type')
    type_elem.text = 'session_created'

    version_elem = etree.SubElement(header, 'version')
    version_elem.text = '1.0'

    correlation_id_elem = etree.SubElement(header, 'correlation_id')
    correlation_id_elem.text = f"corr-{uuid.uuid4()}"

    body = etree.SubElement(root, 'body')
    session = etree.SubElement(body, 'session')

    session_id_elem = etree.SubElement(session, 'session_id')
    session_id_elem.text = session_id

    title_elem = etree.SubElement(session, 'title')
    title_elem.text = title

    start_elem = etree.SubElement(session, 'start_datetime')
    start_elem.text = start_datetime

    end_elem = etree.SubElement(session, 'end_datetime')
    end_elem.text = end_datetime

    location_elem = etree.SubElement(session, 'location')
    location_elem.text = location

    type_session_elem = etree.SubElement(session, 'session_type')
    type_session_elem.text = session_type

    status_elem = etree.SubElement(session, 'status')
    status_elem.text = 'published'

    max_attendees_elem = etree.SubElement(session, 'max_attendees')
    max_attendees_elem.text = str(max_attendees)

    current_attendees_elem = etree.SubElement(session, 'current_attendees')
    current_attendees_elem.text = '0'

    speakers = etree.SubElement(session, 'speakers')
    speaker = etree.SubElement(speakers, 'speaker')

    speaker_id_elem = etree.SubElement(speaker, 'speaker_id')
    speaker_id_elem.text = f"crm-{uuid.uuid4()}"

    speaker_name_elem = etree.SubElement(speaker, 'name')
    speaker_name_elem.text = speaker_name

    speaker_company_elem = etree.SubElement(speaker, 'company')
    speaker_company_elem.text = speaker_company

    outlook_elem = etree.SubElement(session, 'outlook_event_id')
    outlook_elem.text = f"AAMkADk2{uuid.uuid4().hex[:20]}=="

    created_at_elem = etree.SubElement(session, 'created_at')
    created_at_elem.text = datetime.utcnow().isoformat() + "Z"

    return etree.tostring(root, encoding='unicode', pretty_print=True)


def validate_xml(xml_string: str) -> bool:
    try:
        etree.fromstring(xml_string.encode('utf-8'))
        return True
    except etree.XMLSyntaxError as e:
        logger.error(f"Invalid XML: {e}")
        return False


def send_message(xml_message: str):
    try:
        credentials = pika.PlainCredentials(RABBITMQ_USER, RABBITMQ_PASS)

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
            logger.error("Cannot send invalid XML message")
            connection.close()
            return False

        channel.basic_publish(
            exchange=EXCHANGE_NAME,
            routing_key=ROUTING_KEY,
            body=xml_message,
            properties=pika.BasicProperties(
                content_type='application/xml',
                delivery_mode=2
            )
        )

        logger.info(f"Message sent with routing key '{ROUTING_KEY}'")
        connection.close()
        return True

    except pika.exceptions.AMQPConnectionError as e:
        logger.error(f"Failed to connect to RabbitMQ: {e}")
        return False
    except Exception as e:
        logger.error(f"Error sending message: {e}")
        return False


def main():
    session_xml = create_session_xml(
        session_id="sess-uuid-001",
        title="Keynote: AI in de zorgsector",
        start_datetime="2026-05-15T14:00:00Z",
        end_datetime="2026-05-15T15:00:00Z",
        location="Aula A - Campus Jette",
        speaker_name="Dr. Jan Peeters",
        speaker_company="Accenture Belgium",
        session_type="keynote",
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