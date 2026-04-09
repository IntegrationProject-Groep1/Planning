"""
Planning service consumer.
Listens on RabbitMQ for incoming messages and routes them to appropriate handlers.
Supports: calendar.invite, session_created, session_updated, session_deleted, session_view_request
"""

import pika
import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from dotenv import load_dotenv

load_dotenv()

from xml_handlers import parse_message
from xml_models import (
    CalendarInviteMessage,
    SessionCreatedMessage,
    SessionUpdatedMessage,
    SessionDeletedMessage,
    SessionViewRequestMessage,
)
from calendar_service import (
    MessageLog,
    SessionService,
    CalendarInviteService,
    SessionEventService,
    SessionViewRequestService,
)
from graph_service import GraphService
from producer import publish_calendar_invite_confirmed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

# Exchange and queue configuration
CALENDAR_EXCHANGE = os.getenv("CALENDAR_EXCHANGE", "calendar.exchange")
PLANNING_EXCHANGE = os.getenv("PLANNING_EXCHANGE", "planning.exchange")
CALENDAR_QUEUE = "planning.calendar.invite"
SESSION_QUEUE = "planning.session.events"

# Route keys to listen on
CALENDAR_ROUTING_KEY = "calendar.invite"
SESSION_ROUTING_KEYS = ["planning.session.#"]  # All session events


def _require_env(name: str, value: str | None) -> str:
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


# ============================================================================
# MESSAGE HANDLERS
# ============================================================================

def handle_calendar_invite(msg: CalendarInviteMessage, channel, delivery_tag):
    """Handle calendar.invite message."""
    try:
        logger.info(
            "Handling calendar.invite | message_id=%s | session_id=%s | title=%s",
            msg.header.message_id,
            msg.body.session_id,
            msg.body.title,
        )

        # Log message for idempotency
        if not MessageLog.log_message(
            msg.header.message_id,
            "calendar.invite",
            msg.header.source,
            msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate calendar.invite (already processed): %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        # Create/update session from invite
        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
        )

        # Store calendar invite
        CalendarInviteService.create(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            type_=msg.header.type,
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
        )

        # Update message log
        MessageLog.update_message_status(msg.header.message_id, "processed")

        # Create Outlook event (non-blocking — failure is logged, not nacked)
        GraphService.sync_created(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
        )

        # Confirm enrollment back to Frontend
        publish_calendar_invite_confirmed(
            session_id=msg.body.session_id,
            original_message_id=msg.header.message_id,
            status="confirmed",
            correlation_id=msg.header.correlation_id,
        )

        logger.info("calendar.invite processed successfully | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling calendar.invite: %s", e, exc_info=True)
        MessageLog.update_message_status(msg.header.message_id, "failed", str(e))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_created(msg: SessionCreatedMessage, channel, delivery_tag):
    """Handle session_created message (event from other teams)."""
    try:
        logger.info(
            "Handling session_created | message_id=%s | session_id=%s | title=%s",
            msg.header.message_id,
            msg.body.session_id,
            msg.body.title,
        )

        if not MessageLog.log_message(
            msg.header.message_id,
            "session_created",
            msg.header.source,
            msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate session_created: %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        # Create session
        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            session_type=msg.body.session_type or "keynote",
            status=msg.body.status or "published",
            max_attendees=msg.body.max_attendees or 0,
            current_attendees=msg.body.current_attendees or 0,
        )

        # Log event
        SessionEventService.log_event(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            event_type="session_created",
            session_id=msg.body.session_id,
            version=msg.header.version or "1.0",
            correlation_id=msg.header.correlation_id,
            event_data={
                "title": msg.body.title,
                "location": msg.body.location,
                "max_attendees": msg.body.max_attendees,
            },
        )

        MessageLog.update_message_status(msg.header.message_id, "processed")

        logger.info("session_created processed successfully | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling session_created: %s", e, exc_info=True)
        MessageLog.update_message_status(msg.header.message_id, "failed", str(e))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_updated(msg: SessionUpdatedMessage, channel, delivery_tag):
    """Handle session_updated message."""
    try:
        logger.info(
            "Handling session_updated | message_id=%s | session_id=%s",
            msg.header.message_id,
            msg.body.session_id,
        )

        if not MessageLog.log_message(
            msg.header.message_id,
            "session_updated",
            msg.header.source,
            msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate session_updated: %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        # Update session
        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            session_type=msg.body.session_type or "keynote",
            status=msg.body.status or "published",
            max_attendees=msg.body.max_attendees or 0,
            current_attendees=msg.body.current_attendees or 0,
        )

        # Log event
        SessionEventService.log_event(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            event_type="session_updated",
            session_id=msg.body.session_id,
            version=msg.header.version or "1.0",
            correlation_id=msg.header.correlation_id,
            event_data={"title": msg.body.title, "current_attendees": msg.body.current_attendees},
        )

        MessageLog.update_message_status(msg.header.message_id, "processed")

        # Update Outlook event (non-blocking)
        GraphService.sync_updated(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
        )

        logger.info("session_updated processed successfully | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling session_updated: %s", e, exc_info=True)
        MessageLog.update_message_status(msg.header.message_id, "failed", str(e))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_deleted(msg: SessionDeletedMessage, channel, delivery_tag):
    """Handle session_deleted message."""
    try:
        logger.info(
            "Handling session_deleted | message_id=%s | session_id=%s",
            msg.header.message_id,
            msg.body.session_id,
        )

        if not MessageLog.log_message(
            msg.header.message_id,
            "session_deleted",
            msg.header.source,
            msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate session_deleted: %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        # Delete session
        SessionService.delete(
            session_id=msg.body.session_id,
            reason=msg.body.reason or "",
            deleted_by=msg.body.deleted_by or "system",
        )

        # Log event
        SessionEventService.log_event(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            event_type="session_deleted",
            session_id=msg.body.session_id,
            version=msg.header.version or "1.0",
            correlation_id=msg.header.correlation_id,
            event_data={"reason": msg.body.reason, "deleted_by": msg.body.deleted_by},
        )

        MessageLog.update_message_status(msg.header.message_id, "processed")

        # Cancel Outlook event (non-blocking)
        GraphService.sync_deleted(
            session_id=msg.body.session_id,
            reason=msg.body.reason or "Session cancelled",
        )

        logger.info("session_deleted processed successfully | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling session_deleted: %s", e, exc_info=True)
        MessageLog.update_message_status(msg.header.message_id, "failed", str(e))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_view_request(msg: SessionViewRequestMessage, channel, delivery_tag):
    """Handle session_view_request message."""
    try:
        logger.info(
            "Handling session_view_request | message_id=%s | session_id=%s",
            msg.header.message_id,
            msg.body.session_id,
        )

        if not MessageLog.log_message(
            msg.header.message_id,
            "session_view_request",
            msg.header.source,
            msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate session_view_request: %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        # Log request
        SessionViewRequestService.log_request(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            session_id=msg.body.session_id,
            version=msg.header.version or "1.0",
            correlation_id=msg.header.correlation_id,
        )

        MessageLog.update_message_status(msg.header.message_id, "processed")

        logger.info("session_view_request processed successfully | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling session_view_request: %s", e, exc_info=True)
        MessageLog.update_message_status(msg.header.message_id, "failed", str(e))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


# ============================================================================
# MESSAGE ROUTING
# ============================================================================

def route_message(msg, channel, delivery_tag):
    """Route message to appropriate handler based on type."""
    if isinstance(msg, CalendarInviteMessage):
        handle_calendar_invite(msg, channel, delivery_tag)
    elif isinstance(msg, SessionCreatedMessage):
        handle_session_created(msg, channel, delivery_tag)
    elif isinstance(msg, SessionUpdatedMessage):
        handle_session_updated(msg, channel, delivery_tag)
    elif isinstance(msg, SessionDeletedMessage):
        handle_session_deleted(msg, channel, delivery_tag)
    elif isinstance(msg, SessionViewRequestMessage):
        handle_session_view_request(msg, channel, delivery_tag)
    else:
        logger.error("Unknown message type: %s", type(msg))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def on_message(channel, method, properties, body: bytes):
    """RabbitMQ message callback."""
    logger.info("Message received on routing key '%s'", method.routing_key)

    # Parse message
    msg = parse_message(body)

    if msg is None:
        logger.error(
            "Failed to parse message (nack, no requeue)\nContent:\n%s",
            body.decode("utf-8", errors="replace"),
        )
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)
        return

    # Route to handler
    route_message(msg, channel, method.delivery_tag)


def start_consumer():
    """Start the RabbitMQ consumer."""
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

    # Declare exchanges (durable)
    channel.exchange_declare(exchange=CALENDAR_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=PLANNING_EXCHANGE, exchange_type="topic", durable=True)

    # Declare and bind calendar queue
    channel.queue_declare(queue=CALENDAR_QUEUE, durable=True)
    channel.queue_bind(
        queue=CALENDAR_QUEUE, exchange=CALENDAR_EXCHANGE, routing_key=CALENDAR_ROUTING_KEY
    )

    # Declare and bind session events queue
    channel.queue_declare(queue=SESSION_QUEUE, durable=True)
    for routing_key in SESSION_ROUTING_KEYS:
        channel.queue_bind(
            queue=SESSION_QUEUE, exchange=PLANNING_EXCHANGE, routing_key=routing_key
        )

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=CALENDAR_QUEUE, on_message_callback=on_message)
    channel.basic_consume(queue=SESSION_QUEUE, on_message_callback=on_message)

    logger.info(
        "Consumer started | calendar_exchange=%s | planning_exchange=%s | vhost=%s",
        CALENDAR_EXCHANGE,
        PLANNING_EXCHANGE,
        RABBITMQ_VHOST,
    )
    channel.start_consuming()


def start_health_server(port: int = 30050):
    """Start health check HTTP server."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, format, *args):
            pass  # Silence logs

    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("Health endpoint started on port %d", port)


if __name__ == "__main__":
    start_health_server()
    start_consumer()
