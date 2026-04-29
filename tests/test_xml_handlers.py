"""
Tests for XML parsing and validation (xml_handlers.py).
"""

import pytest
from xml_handlers import (
    parse_calendar_invite,
    parse_session_create_request,
    parse_session_created,
    parse_session_updated,
    parse_session_deleted,
    parse_session_view_request,
    parse_message,
    build_session_create_request_xml,
    build_session_created_xml,
    build_session_view_response_xml,
)
from xml_models import (
    CalendarInviteMessage,
    SessionCreateRequestMessage,
    SessionCreatedMessage,
    SessionUpdatedMessage,
    SessionDeletedMessage,
    SessionViewRequestMessage,
)


class TestParseCalendarInvite:
    """Tests for calendar.invite parsing."""

    def test_parse_valid_calendar_invite(self, sample_calendar_invite_xml):
        """Parsing valid calendar.invite should succeed."""
        msg = parse_calendar_invite(sample_calendar_invite_xml)
        assert msg is not None
        assert isinstance(msg, CalendarInviteMessage)
        assert msg.body.session_id == "sess-001"
        assert msg.body.title == "Test Session"

    def test_parse_calendar_invite_malformed_xml(self, malformed_xml):
        """Parsing malformed XML should return None."""
        msg = parse_calendar_invite(malformed_xml)
        assert msg is None

    def test_parse_calendar_invite_missing_header(self, xml_missing_header):
        """Parsing without header should return None."""
        msg = parse_calendar_invite(xml_missing_header)
        assert msg is None

    def test_parse_calendar_invite_missing_required_fields(self, xml_missing_required_fields):
        """Parsing with missing required fields should return None."""
        msg = parse_calendar_invite(xml_missing_required_fields)
        assert msg is None


class TestParseSessionCreated:
    """Tests for session_created parsing."""

    def test_parse_valid_session_created(self, sample_session_created_xml):
        """Parsing valid session_created should succeed."""
        msg = parse_session_created(sample_session_created_xml)
        assert msg is not None
        assert isinstance(msg, SessionCreatedMessage)
        assert msg.body.session_id == "sess-001"
        assert msg.body.max_attendees == 120
        assert msg.body.current_attendees == 0

    def test_parse_session_created_has_all_fields(self, sample_session_created_xml):
        """Parsed session_created should contain all expected fields."""
        msg = parse_session_created(sample_session_created_xml)
        assert msg.header.message_id == "msg-002"
        assert msg.header.type == "session_created"
        assert msg.header.correlation_id == "corr-001"
        assert msg.body.session_type == "keynote"
        assert msg.body.status == "published"


class TestParseSessionCreateRequest:
    """Tests for session_create_request parsing."""

    def test_parse_valid_session_create_request(self, sample_session_create_request_xml):
        """Parsing valid session_create_request should succeed."""
        msg = parse_session_create_request(sample_session_create_request_xml)
        assert msg is not None
        assert isinstance(msg, SessionCreateRequestMessage)
        assert msg.body.session_id == "sess-000"
        assert msg.body.session_type == "workshop"
        assert msg.body.max_attendees == 80


class TestParseSessionUpdated:
    """Tests for session_updated parsing."""

    def test_parse_valid_session_updated(self, sample_session_updated_xml):
        """Parsing valid session_updated should succeed."""
        msg = parse_session_updated(sample_session_updated_xml)
        assert msg is not None
        assert isinstance(msg, SessionUpdatedMessage)
        assert msg.body.session_id == "sess-001"
        assert msg.body.current_attendees == 25


class TestParseSessionDeleted:
    """Tests for session_deleted parsing."""

    def test_parse_valid_session_deleted(self, sample_session_deleted_xml):
        """Parsing valid session_deleted should succeed."""
        msg = parse_session_deleted(sample_session_deleted_xml)
        assert msg is not None
        assert isinstance(msg, SessionDeletedMessage)
        assert msg.body.session_id == "sess-001"
        assert msg.body.reason == "cancelled"
        assert msg.body.deleted_by == "planning-admin"


class TestParseSessionViewRequest:
    """Tests for session_view_request parsing."""

    def test_parse_valid_session_view_request(self, sample_session_view_request_xml):
        """Parsing valid session_view_request should succeed."""
        msg = parse_session_view_request(sample_session_view_request_xml)
        assert msg is not None
        assert isinstance(msg, SessionViewRequestMessage)
        assert msg.body.session_id == "sess-001"


class TestGenericParse:
    """Tests for generic message parser (parse_message)."""

    def test_parse_message_calendar_invite(self, sample_calendar_invite_xml):
        """Generic parser should identify and parse calendar.invite."""
        msg = parse_message(sample_calendar_invite_xml)
        assert isinstance(msg, CalendarInviteMessage)

    def test_parse_message_session_created(self, sample_session_created_xml):
        """Generic parser should identify and parse session_created."""
        msg = parse_message(sample_session_created_xml)
        assert isinstance(msg, SessionCreatedMessage)

    def test_parse_message_session_create_request(self, sample_session_create_request_xml):
        """Generic parser should identify and parse session_create_request."""
        msg = parse_message(sample_session_create_request_xml)
        assert isinstance(msg, SessionCreateRequestMessage)

    def test_parse_message_session_updated(self, sample_session_updated_xml):
        """Generic parser should identify and parse session_updated."""
        msg = parse_message(sample_session_updated_xml)
        assert isinstance(msg, SessionUpdatedMessage)

    def test_parse_message_session_deleted(self, sample_session_deleted_xml):
        """Generic parser should identify and parse session_deleted."""
        msg = parse_message(sample_session_deleted_xml)
        assert isinstance(msg, SessionDeletedMessage)

    def test_parse_message_session_view_request(self, sample_session_view_request_xml):
        """Generic parser should identify and parse session_view_request."""
        msg = parse_message(sample_session_view_request_xml)
        assert isinstance(msg, SessionViewRequestMessage)

    def test_parse_message_malformed_returns_none(self, malformed_xml):
        """Generic parser should return None for malformed XML."""
        msg = parse_message(malformed_xml)
        assert msg is None


class TestBuildSessionCreatedXml:
    """Tests for session_created XML building."""

    def test_build_session_created_xml_returns_string(self):
        """Building session_created should return XML string."""
        xml = build_session_created_xml(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
        )
        assert isinstance(xml, str)
        assert "<message" in xml
        assert "session_created" in xml

    def test_build_session_created_xml_contains_header_fields(self):
        """Built XML should contain required header fields."""
        xml = build_session_created_xml(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
        )
        assert "<message_id>" in xml
        assert "<timestamp>" in xml
        assert "<source>planning</source>" in xml
        assert "<type>session_created</type>" in xml
        assert "<version>1.0</version>" in xml
        assert "<correlation_id>" in xml

    def test_build_session_created_xml_contains_body_fields(self):
        """Built XML should contain required body fields."""
        xml = build_session_created_xml(
            session_id="sess-001",
            title="Test Session",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Room A",
        )
        assert "<session_id>sess-001</session_id>" in xml
        assert "<title>Test Session</title>" in xml
        assert "<start_datetime>" in xml
        assert "<end_datetime>" in xml
        assert "<location>Room A</location>" in xml

    def test_build_session_created_xml_is_valid(self):
        """Built XML should be parseable back."""
        xml = build_session_created_xml(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
        )
        # Should parse without error
        msg = parse_session_created(xml.encode())
        assert msg is not None
        assert msg.body.session_id == "sess-001"
        assert msg.body.title == "Test"


class TestBuildSessionCreateRequestXml:
    """Tests for session_create_request XML building."""

    def test_build_session_create_request_xml_is_valid(self):
        """Built XML should be parseable back."""
        xml = build_session_create_request_xml(
            session_id="sess-123",
            title="Create Me",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="online",
            session_type="panel",
            max_attendees=42,
        )
        msg = parse_session_create_request(xml.encode())
        assert msg is not None
        assert msg.header.type == "session_create_request"
        assert msg.body.session_id == "sess-123"
        assert msg.body.max_attendees == 42


class TestBuildSessionViewResponse:
    """Tests for session_view_response XML building."""

    def test_build_session_view_response_empty_sessions(self):
        """Building response with no sessions should succeed."""
        xml = build_session_view_response_xml(
            request_message_id="req-001",
            requested_session_id="sess-001",
            status="not_found",
            sessions=[],
        )
        assert isinstance(xml, str)
        assert "session_view_response" in xml
        assert "<session_count>0</session_count>" in xml

    def test_build_session_view_response_with_sessions(self):
        """Building response with sessions should include session data."""
        xml = build_session_view_response_xml(
            request_message_id="req-001",
            requested_session_id="sess-001",
            status="ok",
            sessions=[
                {
                    "session_id": "sess-001",
                    "title": "Test",
                    "start_datetime": "2026-05-15T14:00:00Z",
                    "end_datetime": "2026-05-15T15:00:00Z",
                    "location": "online",
                    "session_type": "keynote",
                    "status": "published",
                    "max_attendees": 120,
                    "current_attendees": 10,
                }
            ],
        )
        assert "<session_count>1</session_count>" in xml
        assert "<session_id>sess-001</session_id>" in xml
        assert "<title>Test</title>" in xml
        assert "<max_attendees>120</max_attendees>" in xml

    def test_build_session_view_response_has_request_reference(self):
        """Built response should reference the original request."""
        xml = build_session_view_response_xml(
            request_message_id="req-original-001",
            requested_session_id="sess-001",
            status="ok",
            sessions=[],
        )
        assert "<request_message_id>req-original-001</request_message_id>" in xml
