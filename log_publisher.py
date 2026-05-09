"""
§3.5 Log publisher — sends structured log messages to the central `logs` queue.

Usage:
    from log_publisher import publish_log, action_for_type
    publish_log(channel, "info",  "session",        "Published session_created to planning.exchange. CorrelationID: …")
    publish_log(channel, "error", "xml_validation", "Received session_create_request from frontend. Validation: Failure.")
    publish_log(channel, "error", "system_error",   "Internal Error in handle_calendar_invite: <details>")
"""

import uuid
import logging
from datetime import datetime, timezone

import pika
from lxml import etree

logger = logging.getLogger(__name__)

LOGS_QUEUE = "logs"
_SOURCE = "planning"

# Maps message types to the §3.5 action enum values.
_TYPE_TO_ACTION: dict[str, str] = {
    "session_created":               "session",
    "session_updated":               "session",
    "session_deleted":               "session",
    "session_view_request":          "session",
    "session_view_response":         "session",
    "session_create_request":        "session",
    "session_update_request":        "session",
    "session_delete_request":        "session",
    "session_registration_confirmed":"session",
    "session_occupancy_update":      "session",
    "calendar_invite":               "calendar",
    "calendar_invite_confirmed":     "calendar",
    "calendar.invite":               "calendar",
    "cancel_registration":           "registration",
}


def action_for_type(message_type: str) -> str:
    """Return the §3.5 action enum for a given message type."""
    return _TYPE_TO_ACTION.get(message_type, "session")


def _build_log_xml(level: str, action: str, message: str) -> str:
    root = etree.Element("message")
    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = _SOURCE
    etree.SubElement(header, "type").text = "log"
    etree.SubElement(header, "version").text = "2.0"
    body = etree.SubElement(root, "body")
    etree.SubElement(body, "level").text = level
    etree.SubElement(body, "action").text = action
    etree.SubElement(body, "message").text = message
    return etree.tostring(root, encoding="unicode")


def publish_log(channel, level: str, action: str, message: str) -> None:
    """Publish a §3.5 log message to the `logs` queue via an already-open channel.

    Failures are swallowed and only written to the local logger so that a
    broken logs queue never takes down the main message flow.
    """
    try:
        xml = _build_log_xml(level, action, message)
        channel.basic_publish(
            exchange="",
            routing_key=LOGS_QUEUE,
            body=xml,
            properties=pika.BasicProperties(
                content_type="application/xml",
                delivery_mode=2,
            ),
        )
    except Exception as exc:
        logger.warning("Failed to publish log to '%s': %s", LOGS_QUEUE, exc)
