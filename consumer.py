"""
Planning service consumer.
Listens on RabbitMQ for incoming messages and routes them to appropriate handlers.
Supports: calendar.invite, session_created, session_updated, session_deleted,
          session_create_request, session_update_request, session_delete_request,
          session_view_request
"""

import json
import pika
import os
import logging
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from dotenv import load_dotenv
from lxml import etree

load_dotenv(".env.local", override=True)
load_dotenv()

from xml_handlers import parse_message
from xml_models import (
    CalendarInviteMessage,
    SessionCreatedMessage,
    SessionUpdatedMessage,
    SessionDeletedMessage,
    SessionCreateRequestMessage,
    SessionUpdateRequestMessage,
    SessionDeleteRequestMessage,
    SessionViewRequestMessage,
)
from calendar_service import (
    MessageLog,
    SessionService,
    CalendarInviteService,
    SessionEventService,
    SessionViewRequestService,
    IcsFeedService,
)
from graph_service import GraphService
from token_service import TokenService
from producer import publish_calendar_invite_confirmed

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RABBITMQ_HOST = os.getenv("RABBITMQ_HOST", "localhost")
RABBITMQ_PORT = int(os.getenv("RABBITMQ_PORT", "5672"))
RABBITMQ_USER = os.getenv("RABBITMQ_USER")
RABBITMQ_PASS = os.getenv("RABBITMQ_PASS")
RABBITMQ_VHOST = os.getenv("RABBITMQ_VHOST", "/")

# Shared secret Drupal must send as "Authorization: Bearer <value>"
_API_TOKEN_SECRET = os.getenv("API_TOKEN_SECRET", "")

# Base URL used when building ICS feed links for non-Outlook users
_ICS_BASE_URL = os.getenv("ICS_BASE_URL", "http://localhost:30050")

# Exchange and queue configuration
CALENDAR_EXCHANGE = os.getenv("CALENDAR_EXCHANGE", "calendar.exchange")
PLANNING_EXCHANGE = os.getenv("PLANNING_EXCHANGE", "planning.exchange")
CALENDAR_QUEUE = "planning.calendar.invite"
SESSION_QUEUE = "planning.session.events"

# Route keys to listen on
CALENDAR_ROUTING_KEY = "frontend.to.planning.calendar.invite"
SESSION_ROUTING_KEYS = ["frontend.to.planning.session.#"]


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

        # Store calendar invite (with user_id so the ICS feed can query it)
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
            user_id=msg.body.user_id or None,
        )

        # Update message log
        MessageLog.update_message_status(msg.header.message_id, "processed")

        # Sync to Outlook — only for users with a registered token
        GraphService.sync_created(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            user_id=msg.body.user_id or None,
        )

        # For non-Outlook users: ensure an ICS feed record exists and build the URL
        ics_url = None
        if msg.body.user_id:
            try:
                has_outlook_token = bool(TokenService.get_valid_token(msg.body.user_id))
            except Exception:
                has_outlook_token = False
            if not has_outlook_token:
                feed = IcsFeedService.get_or_create(msg.body.user_id)
                if feed:
                    ics_url = (
                        f"{_ICS_BASE_URL}/ical/{msg.body.user_id}"
                        f"?token={feed['feed_token']}"
                    )
                    logger.info(
                        "ICS feed URL generated | user_id=%s | url=%s",
                        msg.body.user_id,
                        ics_url,
                    )

        # Confirm enrollment back to Frontend (ics_url is None for Outlook users)
        publish_calendar_invite_confirmed(
            session_id=msg.body.session_id,
            original_message_id=msg.header.message_id,
            status="confirmed",
            correlation_id=msg.header.correlation_id,
            ics_url=ics_url,
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


def handle_session_update_request(msg: SessionUpdateRequestMessage, channel, delivery_tag):
    """Handle session_update_request from Drupal/frontend: update DB + sync Graph + publish event."""
    try:
        logger.info(
            "Handling session_update_request | message_id=%s | session_id=%s",
            msg.header.message_id, msg.body.session_id,
        )

        if not MessageLog.log_message(
            msg.header.message_id, "session_update_request",
            msg.header.source, msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate session_update_request: %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            session_type=msg.body.session_type or "keynote",
            status=msg.body.status or "published",
            max_attendees=msg.body.max_attendees or 0,
        )

        SessionEventService.log_event(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            event_type="session_update_request",
            session_id=msg.body.session_id,
            version=msg.header.version or "1.0",
            correlation_id=msg.header.correlation_id,
            event_data={"title": msg.body.title},
        )

        MessageLog.update_message_status(msg.header.message_id, "processed")

        GraphService.sync_updated(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
        )

        from producer import publish_session_updated
        publish_session_updated(
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

        logger.info("session_update_request processed | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling session_update_request: %s", e, exc_info=True)
        MessageLog.update_message_status(msg.header.message_id, "failed", str(e))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_create_request(msg: SessionCreateRequestMessage, channel, delivery_tag):
    """Handle session_create_request from Drupal/frontend: create DB record + publish event."""
    try:
        logger.info(
            "Handling session_create_request | message_id=%s | session_id=%s",
            msg.header.message_id,
            msg.body.session_id,
        )

        if not MessageLog.log_message(
            msg.header.message_id,
            "session_create_request",
            msg.header.source,
            msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate session_create_request: %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        SessionService.create_or_update(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            session_type=msg.body.session_type or "keynote",
            status=msg.body.status or "published",
            max_attendees=msg.body.max_attendees or 0,
            current_attendees=0,
        )

        SessionEventService.log_event(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            event_type="session_create_request",
            session_id=msg.body.session_id,
            version=msg.header.version or "1.0",
            correlation_id=msg.header.correlation_id,
            event_data={"title": msg.body.title},
        )

        MessageLog.update_message_status(msg.header.message_id, "processed")

        from producer import publish_session_created
        publish_session_created(
            session_id=msg.body.session_id,
            title=msg.body.title,
            start_datetime=msg.body.start_datetime,
            end_datetime=msg.body.end_datetime,
            location=msg.body.location or "",
            session_type=msg.body.session_type or "keynote",
            status=msg.body.status or "published",
            max_attendees=msg.body.max_attendees or 0,
            current_attendees=0,
            correlation_id=msg.header.correlation_id,
        )

        logger.info("session_create_request processed | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling session_create_request: %s", e, exc_info=True)
        MessageLog.update_message_status(msg.header.message_id, "failed", str(e))
        channel.basic_nack(delivery_tag=delivery_tag, requeue=False)


def handle_session_delete_request(msg: SessionDeleteRequestMessage, channel, delivery_tag):
    """Handle session_delete_request from Drupal/frontend: delete in DB + cancel Graph + publish event."""
    try:
        logger.info(
            "Handling session_delete_request | message_id=%s | session_id=%s",
            msg.header.message_id, msg.body.session_id,
        )

        if not MessageLog.log_message(
            msg.header.message_id, "session_delete_request",
            msg.header.source, msg.header.timestamp,
            correlation_id=msg.header.correlation_id,
        ):
            logger.warning("Duplicate session_delete_request: %s", msg.header.message_id)
            channel.basic_ack(delivery_tag=delivery_tag)
            return

        SessionService.delete(
            session_id=msg.body.session_id,
            reason=msg.body.reason or "",
            deleted_by=msg.header.source or "frontend",
        )

        SessionEventService.log_event(
            message_id=msg.header.message_id,
            timestamp=msg.header.timestamp,
            source=msg.header.source,
            event_type="session_delete_request",
            session_id=msg.body.session_id,
            version=msg.header.version or "1.0",
            correlation_id=msg.header.correlation_id,
            event_data={"reason": msg.body.reason},
        )

        MessageLog.update_message_status(msg.header.message_id, "processed")

        GraphService.sync_deleted(
            session_id=msg.body.session_id,
            reason=msg.body.reason or "Session cancelled",
        )

        from producer import publish_session_deleted
        publish_session_deleted(
            session_id=msg.body.session_id,
            reason=msg.body.reason or "",
            deleted_by=msg.header.source or "frontend",
            correlation_id=msg.header.correlation_id,
        )

        logger.info("session_delete_request processed | message_id=%s", msg.header.message_id)
        channel.basic_ack(delivery_tag=delivery_tag)

    except Exception as e:
        logger.error("Error handling session_delete_request: %s", e, exc_info=True)
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
    elif isinstance(msg, SessionCreateRequestMessage):
        handle_session_create_request(msg, channel, delivery_tag)
    elif isinstance(msg, SessionUpdateRequestMessage):
        handle_session_update_request(msg, channel, delivery_tag)
    elif isinstance(msg, SessionDeleteRequestMessage):
        handle_session_delete_request(msg, channel, delivery_tag)
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


DEAD_LETTER_EXCHANGE = "planning.dlx"
DEAD_LETTER_QUEUE = "planning.dead_letters"

_RECONNECT_DELAYS = [5, 10, 30, 60, 120]  # seconds between reconnect attempts


def _build_params(user: str, password: str) -> pika.ConnectionParameters:
    return pika.ConnectionParameters(
        host=RABBITMQ_HOST,
        port=RABBITMQ_PORT,
        virtual_host=RABBITMQ_VHOST,
        credentials=pika.PlainCredentials(user, password),
        heartbeat=60,
        blocked_connection_timeout=30,
    )


def _setup_channel(channel) -> None:
    """Declare all exchanges, queues, and bindings (idempotent)."""
    # Dead-letter exchange + queue
    channel.exchange_declare(exchange=DEAD_LETTER_EXCHANGE, exchange_type="fanout", durable=True)
    channel.queue_declare(queue=DEAD_LETTER_QUEUE, durable=True)
    channel.queue_bind(queue=DEAD_LETTER_QUEUE, exchange=DEAD_LETTER_EXCHANGE)

    dlx_args = {
        "x-dead-letter-exchange": DEAD_LETTER_EXCHANGE,
    }

    # Main exchanges
    channel.exchange_declare(exchange=CALENDAR_EXCHANGE, exchange_type="topic", durable=True)
    channel.exchange_declare(exchange=PLANNING_EXCHANGE, exchange_type="topic", durable=True)

    # Calendar queue with DLX
    channel.queue_declare(queue=CALENDAR_QUEUE, durable=True, arguments=dlx_args)
    channel.queue_bind(
        queue=CALENDAR_QUEUE, exchange=CALENDAR_EXCHANGE, routing_key=CALENDAR_ROUTING_KEY
    )

    # Session events queue with DLX
    channel.queue_declare(queue=SESSION_QUEUE, durable=True, arguments=dlx_args)
    for routing_key in SESSION_ROUTING_KEYS:
        channel.queue_bind(
            queue=SESSION_QUEUE, exchange=PLANNING_EXCHANGE, routing_key=routing_key
        )

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=CALENDAR_QUEUE, on_message_callback=on_message)
    channel.basic_consume(queue=SESSION_QUEUE, on_message_callback=on_message)


def start_consumer():
    """Start the RabbitMQ consumer with boot-retry and automatic reconnection."""
    user = _require_env("RABBITMQ_USER", RABBITMQ_USER)
    password = _require_env("RABBITMQ_PASS", RABBITMQ_PASS)
    params = _build_params(user, password)

    attempt = 0
    while True:
        try:
            logger.info(
                "Connecting to RabbitMQ | host=%s port=%s vhost=%s (attempt %d)",
                RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_VHOST, attempt + 1,
            )
            connection = pika.BlockingConnection(params)
            channel = connection.channel()
            _setup_channel(channel)

            logger.info(
                "Consumer started | calendar_exchange=%s | planning_exchange=%s | vhost=%s | dlx=%s",
                CALENDAR_EXCHANGE,
                PLANNING_EXCHANGE,
                RABBITMQ_VHOST,
                DEAD_LETTER_EXCHANGE,
            )
            attempt = 0  # reset after successful connect
            channel.start_consuming()

        except pika.exceptions.AMQPConnectionError as exc:
            delay = _RECONNECT_DELAYS[min(attempt, len(_RECONNECT_DELAYS) - 1)]
            logger.error(
                "RabbitMQ connection lost: %s — reconnecting in %ds (attempt %d)",
                exc, delay, attempt + 1,
            )
            attempt += 1
            time.sleep(delay)

        except pika.exceptions.AMQPChannelError as exc:
            delay = _RECONNECT_DELAYS[min(attempt, len(_RECONNECT_DELAYS) - 1)]
            logger.error(
                "RabbitMQ channel error: %s — reconnecting in %ds (attempt %d)",
                exc, delay, attempt + 1,
            )
            attempt += 1
            time.sleep(delay)

        except KeyboardInterrupt:
            logger.info("Consumer stopped by operator")
            break

        except Exception as exc:
            delay = _RECONNECT_DELAYS[min(attempt, len(_RECONNECT_DELAYS) - 1)]
            logger.error(
                "Unexpected consumer error: %s — reconnecting in %ds (attempt %d)",
                exc, delay, attempt + 1,
                exc_info=True,
            )
            attempt += 1
            time.sleep(delay)


def start_health_server(port: int = 30050):
    """Start HTTP server with health check and token registration endpoint."""

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
            if parsed.path.startswith("/ical/"):
                self._handle_ics_feed(parsed)
            else:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")

        def _handle_ics_feed(self, parsed):
            """
            GET /ical/{user_id}?token={feed_token}

            Returns an RFC 5545 iCalendar file the user can subscribe to from
            any calendar application.  Replace http:// with webcal:// in the
            URL to trigger a direct subscription in apps that support it.
            """
            from ics_service import build_ics

            path_parts = parsed.path.strip("/").split("/")
            # Expect exactly ["ical", "<user_id>"]
            if len(path_parts) != 2 or not path_parts[1]:
                self.send_response(404)
                self.end_headers()
                return

            user_id = path_parts[1]
            params = parse_qs(parsed.query)
            token = params.get("token", [None])[0]

            if not token or not IcsFeedService.validate_token(user_id, token):
                self.send_response(401)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Unauthorized")
                return

            sessions = IcsFeedService.get_user_sessions(user_id)
            ics_bytes = build_ics(sessions, calendar_name=f"Planning – {user_id}")

            self.send_response(200)
            self.send_header("Content-Type", "text/calendar; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="planning-{user_id}.ics"',
            )
            self.send_header("Content-Length", str(len(ics_bytes)))
            self.end_headers()
            self.wfile.write(ics_bytes)

        def do_POST(self):
            if self.path == "/api/tokens":
                self._handle_register_token()
            else:
                self.send_response(404)
                self.end_headers()

        def _handle_register_token(self):
            """
            POST /api/tokens
            Body (JSON):
              {
                "user_id":       "usr_123",
                "access_token":  "eyJ...",
                "refresh_token": "0.A...",
                "expires_in":    3600        // seconds until access_token expires
              }
            Requires header: Authorization: Bearer <API_TOKEN_SECRET>
            """
            if _API_TOKEN_SECRET:
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {_API_TOKEN_SECRET}":
                    self._json_response(401, {"error": "unauthorized"})
                    return

            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
                data = json.loads(body)

                user_id = data.get("user_id", "").strip()
                access_token = data.get("access_token", "").strip()
                refresh_token = data.get("refresh_token", "").strip()
                expires_in = int(data.get("expires_in", 3600))

                if not all([user_id, access_token]):
                    self._json_response(400, {"error": "user_id and access_token are required"})
                    return

                expires_at = datetime.now(tz=timezone.utc).replace(microsecond=0)
                from datetime import timedelta
                expires_at = expires_at + timedelta(seconds=expires_in)

                TokenService.store(user_id, access_token, refresh_token, expires_at)
                logger.info("Token registered via /api/tokens | user_id=%s", user_id)
                self._json_response(200, {"status": "ok", "user_id": user_id})

            except (json.JSONDecodeError, ValueError) as exc:
                self._json_response(400, {"error": str(exc)})
            except Exception as exc:
                logger.error("POST /api/tokens failed: %s", exc, exc_info=True)
                self._json_response(500, {"error": "internal server error"})

        def _json_response(self, status: int, payload: dict):
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # Silence access logs

    server = HTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info("HTTP server started on port %d (health + POST /api/tokens)", port)


if __name__ == "__main__":
    start_health_server()
    start_consumer()
