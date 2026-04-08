"""
Planning service producer.
Sends planning service events to other teams via RabbitMQ.
Supports: session_created, session_updated, session_deleted, session_view_response

Outgoing messages are validated against their XSD schema before publishing.
Failed publishes are retried with exponential backoff (default: 3 attempts).
Invalid XML is blocked and logged — it is never published.
"""

import pika
import os
import time
import logging
from dotenv import load_dotenv

from xml_handlers import (
    build_session_created_xml,
    build_session_updated_xml,
    build_session_deleted_xml,
    build_session_view_response_xml,
)
from xsd_validator import validate_xml

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# RabbitMQ connection settings
RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER", "guest")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS", "guest")

# Exchange configurations
PLANNING_EXCHANGE = "planning.exchange"


def _require_env(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _get_connection():
    """Create a RabbitMQ connection."""
    try:
        user = _require_env("RABBITMQ_USER", RABBITMQ_USER)
        password = _require_env("RABBITMQ_PASS", RABBITMQ_PASS)

        credentials = pika.PlainCredentials(user, password)
        params = pika.ConnectionParameters(
            host=RABBITMQ_HOST,
            port=RABBITMQ_PORT,
            credentials=credentials,
            connection_attempts=3,
            retry_delay=2,
        )

        return pika.BlockingConnection(params)

    except ValueError as e:
        logger.error("%s. Set RABBITMQ_USER and RABBITMQ_PASS in your environment or .env file.", e)
        raise
    except pika.exceptions.AMQPConnectionError as e:
        logger.error("Failed to connect to RabbitMQ: %s", e)
        raise


def _publish_message(xml_message: str, routing_key: str) -> bool:
    """Publish a single XML message to RabbitMQ (one attempt, no retry)."""
    connection = _get_connection()
    try:
        channel = connection.channel()

        channel.exchange_declare(
            exchange=PLANNING_EXCHANGE,
            exchange_type="topic",
            durable=True,
        )

        channel.basic_publish(
            exchange=PLANNING_EXCHANGE,
            routing_key=routing_key,
            body=xml_message,
            properties=pika.BasicProperties(
                content_type="application/xml",
                delivery_mode=2,  # Persistent
            ),
        )

        logger.info("Message published | routing_key=%s", routing_key)
        return True

    finally:
        try:
            connection.close()
        except Exception:
            pass


def _publish_with_validation_and_retry(
    xml_message: str,
    routing_key: str,
    message_type: str,
    max_retries: int = 3,
    initial_delay: float = 1.0,
) -> bool:
    """
    Validate XML against XSD, then publish with exponential backoff retry.

    Steps:
      1. Validate xml_message against the XSD for message_type.
         If invalid → log error, return False immediately (no publish).
      2. Attempt publish up to max_retries times.
         Delay between attempts doubles each time (1s, 2s, 4s, …).

    Returns True on success, False if all attempts fail or XSD is invalid.
    """
    # --- XSD validation gate ---
    valid, xsd_error = validate_xml(xml_message, message_type)
    if not valid:
        logger.error(
            "Outgoing message blocked: XSD validation failed "
            "| message_type=%s | error=%s",
            message_type,
            xsd_error,
        )
        return False

    # --- Publish with retry ---
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            if _publish_message(xml_message, routing_key):
                return True
        except Exception as exc:
            logger.warning(
                "Publish attempt %d/%d failed | routing_key=%s | error=%s",
                attempt,
                max_retries,
                routing_key,
                exc,
            )

        if attempt < max_retries:
            logger.info(
                "Retrying in %.1fs | routing_key=%s", delay, routing_key
            )
            time.sleep(delay)
            delay *= 2

    logger.error(
        "All %d publish attempts exhausted | routing_key=%s | message_type=%s",
        max_retries,
        routing_key,
        message_type,
    )
    return False


# ============================================================================
# PUBLIC API FUNCTIONS
# ============================================================================

def publish_session_created(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str = "",
    session_type: str = "keynote",
    status: str = "published",
    max_attendees: int = 0,
    current_attendees: int = 0,
    correlation_id: str = None,
) -> bool:
    """
    Publish session_created event.

    Returns True on success, False on failure.
    """
    try:
        xml_message = build_session_created_xml(
            session_id=session_id,
            title=title,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            location=location,
            session_type=session_type,
            status=status,
            max_attendees=max_attendees,
            current_attendees=current_attendees,
            correlation_id=correlation_id,
        )

        logger.info("Built XML for session_created:\n%s", xml_message)
        return _publish_with_validation_and_retry(
            xml_message, "planning.session.created", "session_created"
        )

    except Exception as e:
        logger.error("Error publishing session_created: %s", e, exc_info=True)
        return False


def publish_session_updated(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str = "",
    session_type: str = "keynote",
    status: str = "published",
    max_attendees: int = 0,
    current_attendees: int = 0,
    correlation_id: str = None,
) -> bool:
    """
    Publish session_updated event.

    Returns True on success, False on failure.
    """
    try:
        xml_message = build_session_updated_xml(
            session_id=session_id,
            title=title,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            location=location,
            session_type=session_type,
            status=status,
            max_attendees=max_attendees,
            current_attendees=current_attendees,
            correlation_id=correlation_id,
        )

        logger.info("Built XML for session_updated:\n%s", xml_message)
        return _publish_with_validation_and_retry(
            xml_message, "planning.session.updated", "session_updated"
        )

    except Exception as e:
        logger.error("Error publishing session_updated: %s", e, exc_info=True)
        return False


def publish_session_deleted(
    session_id: str,
    reason: str = "",
    deleted_by: str = "planning",
    correlation_id: str = None,
) -> bool:
    """
    Publish session_deleted event.

    Returns True on success, False on failure.
    """
    try:
        xml_message = build_session_deleted_xml(
            session_id=session_id,
            reason=reason,
            deleted_by=deleted_by,
            correlation_id=correlation_id,
        )

        logger.info("Built XML for session_deleted:\n%s", xml_message)
        return _publish_with_validation_and_retry(
            xml_message, "planning.session.deleted", "session_deleted"
        )

    except Exception as e:
        logger.error("Error publishing session_deleted: %s", e, exc_info=True)
        return False


def publish_session_view_response(
    request_message_id: str,
    requested_session_id: str = None,
    status: str = "ok",
    sessions: list = None,
    correlation_id: str = None,
) -> bool:
    """
    Publish session_view_response in response to a view request.

    Args:
        request_message_id: Message ID of the incoming request
        requested_session_id: Session ID that was requested
        status: "ok" or "not_found"
        sessions: List of session dicts to return
        correlation_id: Correlation ID from request

    Returns True on success, False on failure.
    """
    try:
        if sessions is None:
            sessions = []

        xml_message = build_session_view_response_xml(
            request_message_id=request_message_id,
            requested_session_id=requested_session_id,
            status=status,
            sessions=sessions,
            correlation_id=correlation_id,
        )

        logger.info("Built XML for session_view_response:\n%s", xml_message)
        return _publish_with_validation_and_retry(
            xml_message, "planning.session.view_response", "session_view_response"
        )

    except Exception as e:
        logger.error("Error publishing session_view_response: %s", e, exc_info=True)
        return False


# ============================================================================
# DEMO FUNCTIONS
# ============================================================================

def demo_publish_session_created():
    """Demo: publish a session_created event."""
    logger.info("Demo: Publishing session_created...")
    success = publish_session_created(
        session_id="sess-uuid-001",
        title="Keynote: AI in Healthcare",
        start_datetime="2026-05-15T14:00:00Z",
        end_datetime="2026-05-15T15:00:00Z",
        location="Aula A - Campus Jette",
        max_attendees=120,
    )

    if success:
        logger.info("✓ session_created published successfully")
    else:
        logger.error("✗ Failed to publish session_created")


def demo_publish_session_updated():
    """Demo: publish a session_updated event."""
    logger.info("Demo: Publishing session_updated...")
    success = publish_session_updated(
        session_id="sess-uuid-001",
        title="Keynote: AI in Healthcare (Updated)",
        start_datetime="2026-05-15T14:30:00Z",
        end_datetime="2026-05-15T15:30:00Z",
        location="Aula A - Campus Jette",
        max_attendees=150,
        current_attendees=25,
    )

    if success:
        logger.info("✓ session_updated published successfully")
    else:
        logger.error("✗ Failed to publish session_updated")


def demo_publish_session_deleted():
    """Demo: publish a session_deleted event."""
    logger.info("Demo: Publishing session_deleted...")
    success = publish_session_deleted(
        session_id="sess-uuid-001",
        reason="cancelled",
        deleted_by="planning-admin",
    )

    if success:
        logger.info("✓ session_deleted published successfully")
    else:
        logger.error("✗ Failed to publish session_deleted")


def demo_publish_session_view_response():
    """Demo: publish a session_view_response."""
    logger.info("Demo: Publishing session_view_response...")
    success = publish_session_view_response(
        request_message_id="req-msg-001",
        requested_session_id="sess-uuid-001",
        status="ok",
        sessions=[
            {
                "session_id": "sess-uuid-001",
                "title": "Keynote: AI in Healthcare",
                "start_datetime": "2026-05-15T14:00:00Z",
                "end_datetime": "2026-05-15T15:00:00Z",
                "location": "Aula A - Campus Jette",
                "session_type": "keynote",
                "status": "published",
                "max_attendees": 120,
                "current_attendees": 25,
            }
        ],
    )

    if success:
        logger.info("✓ session_view_response published successfully")
    else:
        logger.error("✗ Failed to publish session_view_response")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "created":
            demo_publish_session_created()
        elif sys.argv[1] == "updated":
            demo_publish_session_updated()
        elif sys.argv[1] == "deleted":
            demo_publish_session_deleted()
        elif sys.argv[1] == "response":
            demo_publish_session_view_response()
        else:
            logger.info("Usage: python producer.py [created|updated|deleted|response]")
    else:
        # Run all demos
        demo_publish_session_created()
        demo_publish_session_updated()
        demo_publish_session_deleted()
        demo_publish_session_view_response()