"""
XML message dataclasses for planning service integration.
Represents all message types according to XSD specifications.
"""

from dataclasses import dataclass, asdict
from typing import Optional, List
from datetime import datetime


# ============================================================================
# COMMON TYPES
# ============================================================================

@dataclass
class MessageHeader:
    """Common header for all messages."""
    message_id: str
    timestamp: str
    source: str
    type: str
    version: Optional[str] = "1.0"
    correlation_id: Optional[str] = None


# ============================================================================
# calendar.invite (INCOMING)
# ============================================================================

@dataclass
class CalendarInviteBody:
    """Body of calendar.invite message."""
    session_id: str
    title: str
    start_datetime: str
    end_datetime: str
    location: Optional[str] = None
    user_id: Optional[str] = None


@dataclass
class CalendarInviteMessage:
    """Complete calendar.invite message."""
    header: MessageHeader
    body: CalendarInviteBody

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "header": asdict(self.header),
            "body": asdict(self.body),
        }


# ============================================================================
# session_created (OUTGOING / EVENT)
# ============================================================================

@dataclass
class SessionCreatedBody:
    """Body of session_created message."""
    session_id: str
    title: str
    start_datetime: str
    end_datetime: str
    location: Optional[str] = None
    session_type: Optional[str] = "keynote"
    status: Optional[str] = "published"
    max_attendees: Optional[int] = 0
    current_attendees: Optional[int] = 0


@dataclass
class SessionCreatedMessage:
    """Complete session_created message."""
    header: MessageHeader
    body: SessionCreatedBody

    def to_dict(self) -> dict:
        return {
            "header": asdict(self.header),
            "body": asdict(self.body),
        }


# ============================================================================
# session_updated (OUTGOING / EVENT)
# ============================================================================

@dataclass
class SessionUpdatedBody:
    """Body of session_updated message."""
    session_id: str
    title: str
    start_datetime: str
    end_datetime: str
    location: Optional[str] = None
    session_type: Optional[str] = "keynote"
    status: Optional[str] = "published"
    max_attendees: Optional[int] = 0
    current_attendees: Optional[int] = 0


@dataclass
class SessionUpdatedMessage:
    """Complete session_updated message."""
    header: MessageHeader
    body: SessionUpdatedBody

    def to_dict(self) -> dict:
        return {
            "header": asdict(self.header),
            "body": asdict(self.body),
        }


# ============================================================================
# session_deleted (OUTGOING / EVENT)
# ============================================================================

@dataclass
class SessionDeletedBody:
    """Body of session_deleted message."""
    session_id: str
    reason: Optional[str] = None
    deleted_by: Optional[str] = None


@dataclass
class SessionDeletedMessage:
    """Complete session_deleted message."""
    header: MessageHeader
    body: SessionDeletedBody

    def to_dict(self) -> dict:
        return {
            "header": asdict(self.header),
            "body": asdict(self.body),
        }


# ============================================================================
# session_view_request (INCOMING)
# ============================================================================

@dataclass
class SessionViewRequestBody:
    """Body of session_view_request message."""
    session_id: Optional[str] = None


@dataclass
class SessionViewRequestMessage:
    """Complete session_view_request message."""
    header: MessageHeader
    body: SessionViewRequestBody

    def to_dict(self) -> dict:
        return {
            "header": asdict(self.header),
            "body": asdict(self.body),
        }


# ============================================================================
# session_view_response (OUTGOING / RESPONSE)
# ============================================================================

@dataclass
class SessionInfo:
    """Session details in view response."""
    session_id: str
    title: Optional[str] = None
    start_datetime: Optional[str] = None
    end_datetime: Optional[str] = None
    location: Optional[str] = None
    session_type: Optional[str] = None
    status: Optional[str] = None
    max_attendees: Optional[int] = None
    current_attendees: Optional[int] = None


@dataclass
class SessionViewResponseBody:
    """Body of session_view_response message."""
    request_message_id: str
    requested_session_id: Optional[str]
    status: str  # "ok" or "not_found"
    session_count: int
    sessions: List[SessionInfo]


@dataclass
class SessionViewResponseMessage:
    """Complete session_view_response message."""
    header: MessageHeader
    body: SessionViewResponseBody

    def to_dict(self) -> dict:
        return {
            "header": asdict(self.header),
            "body": {
                "request_message_id": self.body.request_message_id,
                "requested_session_id": self.body.requested_session_id,
                "status": self.body.status,
                "session_count": self.body.session_count,
                "sessions": [asdict(s) for s in self.body.sessions],
            },
        }


# ============================================================================
# calendar.invite.confirmed (OUTGOING / RESPONSE)
# ============================================================================

@dataclass
class CalendarInviteConfirmedBody:
    """Body of calendar.invite.confirmed message."""
    session_id: str
    original_message_id: str
    status: str  # "confirmed" | "failed"


@dataclass
class CalendarInviteConfirmedMessage:
    """Complete calendar.invite.confirmed message."""
    header: MessageHeader
    body: CalendarInviteConfirmedBody

    def to_dict(self) -> dict:
        return {
            "header": asdict(self.header),
            "body": asdict(self.body),
        }


# ============================================================================
# MESSAGE TYPES MAPPING
# ============================================================================

MESSAGE_TYPES = {
    "calendar.invite": CalendarInviteMessage,
    "calendar.invite.confirmed": CalendarInviteConfirmedMessage,
    "session_created": SessionCreatedMessage,
    "session_updated": SessionUpdatedMessage,
    "session_deleted": SessionDeletedMessage,
    "session_view_request": SessionViewRequestMessage,
    "session_view_response": SessionViewResponseMessage,
}
