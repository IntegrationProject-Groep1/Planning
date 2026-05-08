import pika
import os
import logging
import uuid
import json
from functools import lru_cache
from pathlib import Path
from datetime import datetime, timezone
from lxml import etree
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Master UUID Storage (voor correlatie van gerelateerde berichten)
MASTER_UUID_FILE = Path(__file__).resolve().parent / ".master_uuids.json"


class MasterUUIDManager:
    """Beheert Master UUIDs (correlation IDs) voor sessies."""
    
    @staticmethod
    def _load_uuids() -> dict:
        """Laad bestaande Master UUIDs van schijf."""
        if MASTER_UUID_FILE.exists():
            try:
                with open(MASTER_UUID_FILE, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return {}
        return {}
    
    @staticmethod
    def _save_uuids(uuids: dict) -> None:
        """Sla Master UUIDs op schijf op."""
        try:
            with open(MASTER_UUID_FILE, "w") as f:
                json.dump(uuids, f, indent=2)
        except IOError as e:
            logger.error(f"Fout bij opslaan Master UUIDs: {e}")
    
    @staticmethod
    def get_or_create(session_id: str) -> str:
        """
        Haal bestaande Master UUID op of creëer er een nieuwe.
        
        Args:
            session_id: De unieke identifier van de sessie
            
        Returns:
            De Master UUID (correlation_id) voor deze sessie
        """
        uuids = MasterUUIDManager._load_uuids()
        
        if session_id not in uuids:
            uuids[session_id] = str(uuid.uuid4())
            MasterUUIDManager._save_uuids(uuids)
            logger.info(f"Nieuwe Master UUID gemaakt voor sessie {session_id}: {uuids[session_id]}")
        
        return uuids[session_id]
    
    @staticmethod
    def get(session_id: str) -> str | None:
        """Haal bestaande Master UUID op (geeft None als niet bestaat)."""
        uuids = MasterUUIDManager._load_uuids()
        return uuids.get(session_id)

# RabbitMQ connection settings
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")

# Exchange and routing key (with planning prefix per new infra standard)
EXCHANGE_NAME = 'planning.exchange'
ROUTING_KEY_CREATED = 'planning.session.created'
ROUTING_KEY_UPDATED = 'planning.session.updated'
ROUTING_KEY_DELETED = 'planning.session.deleted'
ROUTING_KEY_VIEW_REQUEST = 'planning.session.view.request'
ROUTING_KEY_VIEW_RESPONSE = 'planning.session.view.response'
XMLNS = "urn:integration:planning:v1"
_XSD_BY_TYPE = {
    "session_created": "session_created.xsd",
    "session_updated": "session_updated.xsd",
    "session_deleted": "session_deleted.xsd",
    "session_view_request": "session_view_request.xsd",
}


def _require_env(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _build_message_root(message_type: str, correlation_id: str | None = None) -> tuple[etree._Element, etree._Element]:
    """Create common message/header envelope and return (root, body).
    
    Args:
        message_type: Type van het bericht (e.g., 'session_created')
        correlation_id: Master UUID voor tracering. Indien niet gegeven, wordt er een nieuwe aangemaakt.
    """
    root = etree.Element("message", xmlns=XMLNS)

    header = etree.SubElement(root, "header")

    message_id_elem = etree.SubElement(header, "message_id")
    message_id_elem.text = str(uuid.uuid4())

    timestamp_elem = etree.SubElement(header, "timestamp")
    timestamp_elem.text = datetime.now(timezone.utc).isoformat()

    source_elem = etree.SubElement(header, "source")
    source_elem.text = "planning"

    type_elem = etree.SubElement(header, "type")
    type_elem.text = message_type

    version_elem = etree.SubElement(header, "version")
    version_elem.text = "2.0"

    correlation_id_elem = etree.SubElement(header, "correlation_id")
    # Gebruik gegeven correlation_id of creëer een nieuwe als fallback
    correlation_id_elem.text = correlation_id or str(uuid.uuid4())

    body = etree.SubElement(root, "body")
    return root, body


def create_session_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str,
    max_attendees: int = 120,
    current_attendees: int = 0
) -> str:
    """Create a session.created XML message with required header/body fields.
    
    Genereert een nieuwe Master UUID voor deze sessie en slaat die op voor toekomstige updates.
    """
    # Maak of haal Master UUID op voor deze sessie
    master_uuid = MasterUUIDManager.get_or_create(session_id)
    
    root, body = _build_message_root("session_created", correlation_id=master_uuid)

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


def create_session_updated_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str,
    session_type: str = "keynote",
    status: str = "published",
    max_attendees: int | None = None,
    current_attendees: int | None = None,
) -> str:
    """Create a session.updated XML message for integration updates.
    
    Gebruikt dezelfde Master UUID als het originele session_created bericht.
    """
    # Haal bestaande Master UUID op voor deze sessie
    master_uuid = MasterUUIDManager.get(session_id)
    if not master_uuid:
        logger.warning(f"Geen Master UUID gevonden voor sessie {session_id}, maak nieuwe aan")
        master_uuid = MasterUUIDManager.get_or_create(session_id)
    
    root, body = _build_message_root("session_updated", correlation_id=master_uuid)

    etree.SubElement(body, "session_id").text = session_id
    etree.SubElement(body, "title").text = title
    etree.SubElement(body, "start_datetime").text = start_datetime
    etree.SubElement(body, "end_datetime").text = end_datetime
    etree.SubElement(body, "location").text = location
    etree.SubElement(body, "session_type").text = session_type
    etree.SubElement(body, "status").text = status

    if max_attendees is not None:
        etree.SubElement(body, "max_attendees").text = str(max_attendees)
    if current_attendees is not None:
        etree.SubElement(body, "current_attendees").text = str(current_attendees)

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def create_session_deleted_xml(
    session_id: str,
    reason: str | None = None,
    deleted_by: str | None = None,
) -> str:
    """Create a session.deleted XML message for integration deletes.
    
    Gebruikt dezelfde Master UUID als het originele session_created bericht.
    """
    # Haal bestaande Master UUID op voor deze sessie
    master_uuid = MasterUUIDManager.get(session_id)
    if not master_uuid:
        logger.warning(f"Geen Master UUID gevonden voor sessie {session_id}, maak nieuwe aan")
        master_uuid = MasterUUIDManager.get_or_create(session_id)
    
    root, body = _build_message_root("session_deleted", correlation_id=master_uuid)

    etree.SubElement(body, "session_id").text = session_id
    if reason:
        etree.SubElement(body, "reason").text = reason
    if deleted_by:
        etree.SubElement(body, "deleted_by").text = deleted_by

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def create_session_view_request_xml(session_id: str | None = None) -> str:
    """Create a session.view.request XML message (single session or all sessions)."""
    root, body = _build_message_root("session_view_request")

    if session_id:
        etree.SubElement(body, "session_id").text = session_id

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def _strip_ns(root: etree._Element) -> etree._Element:
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    return root


@lru_cache(maxsize=None)
def _load_schema(schema_filename: str) -> etree.XMLSchema:
    schema_path = Path(__file__).resolve().parent / "xsd" / schema_filename
    with schema_path.open("rb") as f:
        return etree.XMLSchema(etree.parse(f))


def validate_xml(xml_string: str) -> bool:
    try:
        root_with_ns = etree.fromstring(xml_string.encode("utf-8"))

        # Keep generic XML validation behavior for non-message payloads.
        root = _strip_ns(etree.fromstring(xml_string.encode("utf-8")))
        message_type = root.findtext("header/type")
        if not message_type:
            return True

        schema_filename = _XSD_BY_TYPE.get(message_type)
        if not schema_filename:
            logger.error("Unsupported message type for schema validation: %s", message_type)
            return False

        schema = _load_schema(schema_filename)
        if not schema.validate(root_with_ns):
            schema_error = schema.error_log.last_error
            logger.error(
                "XML failed XSD validation for type '%s': %s",
                message_type,
                schema_error,
            )
            return False

        return True
    except etree.XMLSyntaxError as e:
        logger.error("Invalid XML: %s", e)
        return False
    except (OSError, etree.XMLSchemaParseError) as e:
        logger.error("Could not load/parse XSD schema: %s", e)
        return False


def send_message(xml_message: str, routing_key: str = ROUTING_KEY_CREATED):
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
            logger.error("Cannot send invalid XML message\nPayload:\n%s", xml_message)
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

        logger.info("Message sent with routing key '%s'", routing_key)
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
    # VOORBEELD: Een sessie aanmaken en updaten
    SESSION_ID = "sess-uuid-001"
    
    # 1. Sessie AANMAKEN - dit genereert een nieuwe Master UUID
    logger.info("=" * 60)
    logger.info("1. SESSIE AANMAKEN (session_created)")
    logger.info("=" * 60)
    session_xml = create_session_xml(
        session_id=SESSION_ID,
        title="Keynote: AI in healthcare",
        start_datetime="2026-05-15T14:00:00Z",
        end_datetime="2026-05-15T15:00:00Z",
        location="online",
        max_attendees=120
    )
    logger.info(session_xml)
    send_message(session_xml, routing_key=ROUTING_KEY_CREATED)
    
    # 2. Sessie UPDATEN - gebruikt DEZELFDE Master UUID
    logger.info("\n" + "=" * 60)
    logger.info("2. SESSIE UPDATEN (session_updated)")
    logger.info("=" * 60)
    updated_xml = create_session_updated_xml(
        session_id=SESSION_ID,
        title="Keynote: AI in healthcare (BIJGEWERKT)",
        start_datetime="2026-05-15T14:00:00Z",
        end_datetime="2026-05-15T16:00:00Z",  # Verlengd!
        location="online",
        current_attendees=45
    )
    logger.info(updated_xml)
    send_message(updated_xml, routing_key=ROUTING_KEY_UPDATED)
    
    # 3. Sessie VERWIJDEREN - gebruikt DEZELFDE Master UUID
    logger.info("\n" + "=" * 60)
    logger.info("3. SESSIE VERWIJDEREN (session_deleted)")
    logger.info("=" * 60)
    deleted_xml = create_session_deleted_xml(
        session_id=SESSION_ID,
        reason="Omboeken naar ander moment",
        deleted_by="admin@planning.service"
    )
    logger.info(deleted_xml)
    send_message(deleted_xml, routing_key=ROUTING_KEY_DELETED)
    
    logger.info("\n✓ Alle berichten hebben dezelfde Master UUID (correlation_id)!")


if __name__ == "__main__":
    main()