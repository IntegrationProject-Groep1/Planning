"""
XML message parsing and building utilities.
Handles parsing of all incoming message types and building response messages.
"""

import logging
from typing import Optional, Union
from lxml import etree
import uuid
from datetime import datetime, timezone

from xml_models import (
    MessageHeader,
    CalendarInviteMessage,
    CalendarInviteBody,
    SessionCreatedMessage,
    SessionCreatedBody,
    SessionUpdatedMessage,
    SessionUpdatedBody,
    SessionDeletedMessage,
    SessionDeletedBody,
    SessionViewRequestMessage,
    SessionViewRequestBody,
    SessionViewResponseMessage,
    SessionViewResponseBody,
    SessionInfo,
)

logger = logging.getLogger(__name__)

XMLNS = "urn:integration:planning:v1"


def _strip_ns(root: etree._Element) -> etree._Element:
    """Remove namespace prefixes from all element tags."""
    for elem in root.iter():
        elem.tag = etree.QName(elem.tag).localname
    return root


def _get_text(elem: etree._Element, tag: str, required: bool = False) -> Optional[str]:
    """
    Safely extract text from an element.
    Raises ValueError if required field is missing.
    """
    child = elem.find(tag)
    if child is None:
        if required:
            raise ValueError(f"Required field missing: {tag}")
        return None
    return child.text


def _get_int(elem: etree._Element, tag: str, required: bool = False, default: int = 0) -> int:
    """Safely extract integer from an element."""
    text = _get_text(elem, tag, required=required)
    if text is None:
        return default
    try:
        return int(text)
    except ValueError:
        logger.warning(f"Invalid integer value for {tag}: {text}")
        return default


# ============================================================================
# PARSING FUNCTIONS
# ============================================================================

def parse_calendar_invite(xml_bytes: bytes) -> Optional[CalendarInviteMessage]:
    """Parse and validate calendar.invite message."""
    try:
        root = _strip_ns(etree.fromstring(xml_bytes))

        header_elem = root.find("header")
        body_elem = root.find("body")

        if header_elem is None or body_elem is None:
            logger.error("Missing header or body in calendar.invite")
            return None

        # Parse header
        header = MessageHeader(
            message_id=_get_text(header_elem, "message_id", required=True),
            timestamp=_get_text(header_elem, "timestamp", required=True),
            source=_get_text(header_elem, "source", required=True),
            type=_get_text(header_elem, "type", required=True),
            version=_get_text(header_elem, "version"),
            correlation_id=_get_text(header_elem, "correlation_id"),
        )

        # Parse body
        body = CalendarInviteBody(
            session_id=_get_text(body_elem, "session_id", required=True),
            title=_get_text(body_elem, "title", required=True),
            start_datetime=_get_text(body_elem, "start_datetime", required=True),
            end_datetime=_get_text(body_elem, "end_datetime", required=True),
            location=_get_text(body_elem, "location"),
        )

        return CalendarInviteMessage(header=header, body=body)

    except etree.XMLSyntaxError as e:
        logger.error(f"Malformed XML in calendar.invite: {e}")
        return None
    except ValueError as e:
        logger.error(f"Validation error in calendar.invite: {e}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error parsing calendar.invite: {e}")
        return None


def parse_session_created(xml_bytes: bytes) -> Optional[SessionCreatedMessage]:
    """Parse and validate session_created message."""
    try:
        root = _strip_ns(etree.fromstring(xml_bytes))
        header_elem = root.find("header")
        body_elem = root.find("body")

        if header_elem is None or body_elem is None:
            logger.error("Missing header or body in session_created")
            return None

        header = MessageHeader(
            message_id=_get_text(header_elem, "message_id", required=True),
            timestamp=_get_text(header_elem, "timestamp", required=True),
            source=_get_text(header_elem, "source", required=True),
            type=_get_text(header_elem, "type", required=True),
            version=_get_text(header_elem, "version"),
            correlation_id=_get_text(header_elem, "correlation_id"),
        )

        body = SessionCreatedBody(
            session_id=_get_text(body_elem, "session_id", required=True),
            title=_get_text(body_elem, "title", required=True),
            start_datetime=_get_text(body_elem, "start_datetime", required=True),
            end_datetime=_get_text(body_elem, "end_datetime", required=True),
            location=_get_text(body_elem, "location"),
            session_type=_get_text(body_elem, "session_type") or "keynote",
            status=_get_text(body_elem, "status") or "published",
            max_attendees=_get_int(body_elem, "max_attendees", default=0),
            current_attendees=_get_int(body_elem, "current_attendees", default=0),
        )

        return SessionCreatedMessage(header=header, body=body)

    except (etree.XMLSyntaxError, ValueError, Exception) as e:
        logger.error(f"Error parsing session_created: {e}")
        return None


def parse_session_updated(xml_bytes: bytes) -> Optional[SessionUpdatedMessage]:
    """Parse and validate session_updated message."""
    try:
        root = _strip_ns(etree.fromstring(xml_bytes))
        header_elem = root.find("header")
        body_elem = root.find("body")

        if header_elem is None or body_elem is None:
            logger.error("Missing header or body in session_updated")
            return None

        header = MessageHeader(
            message_id=_get_text(header_elem, "message_id", required=True),
            timestamp=_get_text(header_elem, "timestamp", required=True),
            source=_get_text(header_elem, "source", required=True),
            type=_get_text(header_elem, "type", required=True),
            version=_get_text(header_elem, "version"),
            correlation_id=_get_text(header_elem, "correlation_id"),
        )

        body = SessionUpdatedBody(
            session_id=_get_text(body_elem, "session_id", required=True),
            title=_get_text(body_elem, "title", required=True),
            start_datetime=_get_text(body_elem, "start_datetime", required=True),
            end_datetime=_get_text(body_elem, "end_datetime", required=True),
            location=_get_text(body_elem, "location"),
            session_type=_get_text(body_elem, "session_type") or "keynote",
            status=_get_text(body_elem, "status") or "published",
            max_attendees=_get_int(body_elem, "max_attendees", default=0),
            current_attendees=_get_int(body_elem, "current_attendees", default=0),
        )

        return SessionUpdatedMessage(header=header, body=body)

    except (etree.XMLSyntaxError, ValueError, Exception) as e:
        logger.error(f"Error parsing session_updated: {e}")
        return None


def parse_session_deleted(xml_bytes: bytes) -> Optional[SessionDeletedMessage]:
    """Parse and validate session_deleted message."""
    try:
        root = _strip_ns(etree.fromstring(xml_bytes))
        header_elem = root.find("header")
        body_elem = root.find("body")

        if header_elem is None or body_elem is None:
            logger.error("Missing header or body in session_deleted")
            return None

        header = MessageHeader(
            message_id=_get_text(header_elem, "message_id", required=True),
            timestamp=_get_text(header_elem, "timestamp", required=True),
            source=_get_text(header_elem, "source", required=True),
            type=_get_text(header_elem, "type", required=True),
            version=_get_text(header_elem, "version"),
            correlation_id=_get_text(header_elem, "correlation_id"),
        )

        body = SessionDeletedBody(
            session_id=_get_text(body_elem, "session_id", required=True),
            reason=_get_text(body_elem, "reason"),
            deleted_by=_get_text(body_elem, "deleted_by"),
        )

        return SessionDeletedMessage(header=header, body=body)

    except (etree.XMLSyntaxError, ValueError, Exception) as e:
        logger.error(f"Error parsing session_deleted: {e}")
        return None


def parse_session_view_request(xml_bytes: bytes) -> Optional[SessionViewRequestMessage]:
    """Parse and validate session_view_request message."""
    try:
        root = _strip_ns(etree.fromstring(xml_bytes))
        header_elem = root.find("header")
        body_elem = root.find("body")

        if header_elem is None or body_elem is None:
            logger.error("Missing header or body in session_view_request")
            return None

        header = MessageHeader(
            message_id=_get_text(header_elem, "message_id", required=True),
            timestamp=_get_text(header_elem, "timestamp", required=True),
            source=_get_text(header_elem, "source", required=True),
            type=_get_text(header_elem, "type", required=True),
            version=_get_text(header_elem, "version"),
            correlation_id=_get_text(header_elem, "correlation_id"),
        )

        body = SessionViewRequestBody(
            session_id=_get_text(body_elem, "session_id"),
        )

        return SessionViewRequestMessage(header=header, body=body)

    except (etree.XMLSyntaxError, ValueError, Exception) as e:
        logger.error(f"Error parsing session_view_request: {e}")
        return None


# ============================================================================
# BUILDING FUNCTIONS (XML generation)
# ============================================================================

def build_session_created_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str = "",
    session_type: str = "keynote",
    status: str = "published",
    max_attendees: int = 0,
    current_attendees: int = 0,
    correlation_id: Optional[str] = None,
) -> str:
    """Build session_created XML message."""
    root = etree.Element("message", xmlns=XMLNS)

    # Header
    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = "session_created"
    etree.SubElement(header, "version").text = "1.0"
    etree.SubElement(header, "correlation_id").text = correlation_id or str(uuid.uuid4())

    # Body
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


def build_session_updated_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str = "",
    session_type: str = "keynote",
    status: str = "published",
    max_attendees: int = 0,
    current_attendees: int = 0,
    correlation_id: Optional[str] = None,
) -> str:
    """Build session_updated XML message."""
    root = etree.Element("message", xmlns=XMLNS)

    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = "session_updated"
    etree.SubElement(header, "version").text = "1.0"
    etree.SubElement(header, "correlation_id").text = correlation_id or str(uuid.uuid4())

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


def build_session_deleted_xml(
    session_id: str,
    reason: str = "",
    deleted_by: str = "planning",
    correlation_id: Optional[str] = None,
) -> str:
    """Build session_deleted XML message."""
    root = etree.Element("message", xmlns=XMLNS)

    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = "session_deleted"
    etree.SubElement(header, "version").text = "1.0"
    etree.SubElement(header, "correlation_id").text = correlation_id or str(uuid.uuid4())

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "session_id").text = session_id
    etree.SubElement(body, "reason").text = reason
    etree.SubElement(body, "deleted_by").text = deleted_by

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def build_session_view_response_xml(
    request_message_id: str,
    requested_session_id: Optional[str],
    status: str,
    sessions: list,
    correlation_id: Optional[str] = None,
) -> str:
    """Build session_view_response XML message.
    
    Args:
        request_message_id: Message ID of the incoming request
        requested_session_id: Requested session ID (can be None)
        status: "ok" or "not_found"
        sessions: List of dicts with session details
        correlation_id: Correlation ID from request
    """
    root = etree.Element("message", xmlns=XMLNS)

    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = "session_view_response"
    etree.SubElement(header, "version").text = "1.0"
    etree.SubElement(header, "correlation_id").text = correlation_id or str(uuid.uuid4())

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "request_message_id").text = request_message_id
    if requested_session_id:
        etree.SubElement(body, "requested_session_id").text = requested_session_id
    etree.SubElement(body, "status").text = status
    etree.SubElement(body, "session_count").text = str(len(sessions))

    sessions_elem = etree.SubElement(body, "sessions")
    for session in sessions:
        session_elem = etree.SubElement(sessions_elem, "session")
        etree.SubElement(session_elem, "session_id").text = session.get("session_id", "")
        if session.get("title"):
            etree.SubElement(session_elem, "title").text = session["title"]
        if session.get("start_datetime"):
            etree.SubElement(session_elem, "start_datetime").text = session["start_datetime"]
        if session.get("end_datetime"):
            etree.SubElement(session_elem, "end_datetime").text = session["end_datetime"]
        if session.get("location"):
            etree.SubElement(session_elem, "location").text = session["location"]
        if session.get("session_type"):
            etree.SubElement(session_elem, "session_type").text = session["session_type"]
        if session.get("status"):
            etree.SubElement(session_elem, "status").text = session["status"]
        if session.get("max_attendees") is not None:
            etree.SubElement(session_elem, "max_attendees").text = str(session["max_attendees"])
        if session.get("current_attendees") is not None:
            etree.SubElement(session_elem, "current_attendees").text = str(session["current_attendees"])

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def build_calendar_invite_confirmed_xml(
    session_id: str,
    original_message_id: str,
    status: str = "confirmed",
    correlation_id: Optional[str] = None,
) -> str:
    """Build calendar.invite.confirmed XML message (outgoing response to Frontend)."""
    root = etree.Element("message", xmlns=XMLNS)

    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = "planning"
    etree.SubElement(header, "type").text = "calendar.invite.confirmed"
    etree.SubElement(header, "version").text = "1.0"
    etree.SubElement(header, "correlation_id").text = correlation_id or str(uuid.uuid4())

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "session_id").text = session_id
    etree.SubElement(body, "original_message_id").text = original_message_id
    etree.SubElement(body, "status").text = status

    return etree.tostring(root, encoding="unicode", pretty_print=True)


def build_calendar_invite_xml(
    session_id: str,
    title: str,
    start_datetime: str,
    end_datetime: str,
    location: str = "",
    source: str = "frontend",
) -> str:
    """Build a calendar.invite XML message (outgoing from the frontend demo)."""
    root = etree.Element("message", xmlns=XMLNS)

    header = etree.SubElement(root, "header")
    etree.SubElement(header, "message_id").text = str(uuid.uuid4())
    etree.SubElement(header, "timestamp").text = datetime.now(timezone.utc).isoformat()
    etree.SubElement(header, "source").text = source
    etree.SubElement(header, "type").text = "calendar.invite"

    body = etree.SubElement(root, "body")
    etree.SubElement(body, "session_id").text = session_id
    etree.SubElement(body, "title").text = title
    etree.SubElement(body, "start_datetime").text = start_datetime
    etree.SubElement(body, "end_datetime").text = end_datetime
    if location:
        etree.SubElement(body, "location").text = location

    return etree.tostring(root, encoding="unicode", pretty_print=True)


# ============================================================================
# GENERIC PARSER
# ============================================================================

def parse_message(xml_bytes: bytes) -> Optional[Union[
    CalendarInviteMessage,
    SessionCreatedMessage,
    SessionUpdatedMessage,
    SessionDeletedMessage,
    SessionViewRequestMessage,
]]:
    """
    Parse any message type based on its 'type' field.
    Returns appropriate message object or None on error.
    """
    try:
        root = _strip_ns(etree.fromstring(xml_bytes))
        header_elem = root.find("header")

        if header_elem is None:
            logger.error("Missing header element")
            return None

        msg_type = _get_text(header_elem, "type")

        if msg_type == "calendar.invite":
            return parse_calendar_invite(xml_bytes)
        elif msg_type == "session_created":
            return parse_session_created(xml_bytes)
        elif msg_type == "session_updated":
            return parse_session_updated(xml_bytes)
        elif msg_type == "session_deleted":
            return parse_session_deleted(xml_bytes)
        elif msg_type == "session_view_request":
            return parse_session_view_request(xml_bytes)
        else:
            logger.warning(f"Unknown message type: {msg_type}")
            return None

    except Exception as e:
        logger.error(f"Error in generic message parser: {e}")
        return None
