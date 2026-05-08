"""
Tests for XSD validation (xsd_validator.py).
Covers valid messages, invalid messages, unknown types, and edge cases.
"""

import pytest
from xsd_validator import validate_xml, validate_or_raise


# ---------------------------------------------------------------------------
# Fixtures – valid XML for each outgoing message type
# ---------------------------------------------------------------------------

VALID_SESSION_CREATED = b"""<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440000</message_id>
    <timestamp>2026-05-15T09:00:00Z</timestamp>
    <source>planning</source>
    <type>session_created</type>
    <version>1.0</version>
    <correlation_id>corr-001</correlation_id>
  </header>
  <body>
    <session_id>sess-001</session_id>
    <title>Keynote: AI in Healthcare</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>Aula A</location>
    <session_type>keynote</session_type>
    <status>published</status>
    <max_attendees>120</max_attendees>
    <current_attendees>0</current_attendees>
  </body>
</message>"""

VALID_SESSION_UPDATED = b"""<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440001</message_id>
    <timestamp>2026-05-15T09:30:00Z</timestamp>
    <source>planning</source>
    <type>session_updated</type>
    <version>1.0</version>
    <correlation_id>corr-002</correlation_id>
  </header>
  <body>
    <session_id>sess-001</session_id>
    <title>Keynote (Updated)</title>
    <start_datetime>2026-05-15T14:30:00Z</start_datetime>
    <end_datetime>2026-05-15T15:30:00Z</end_datetime>
    <max_attendees>150</max_attendees>
    <current_attendees>25</current_attendees>
  </body>
</message>"""

VALID_SESSION_DELETED = b"""<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440002</message_id>
    <timestamp>2026-05-15T10:00:00Z</timestamp>
    <source>planning</source>
    <type>session_deleted</type>
    <version>1.0</version>
    <correlation_id>corr-003</correlation_id>
  </header>
  <body>
    <session_id>sess-001</session_id>
    <reason>cancelled</reason>
    <deleted_by>planning-admin</deleted_by>
  </body>
</message>"""

VALID_SESSION_VIEW_RESPONSE = b"""<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>550e8400-e29b-41d4-a716-446655440003</message_id>
    <timestamp>2026-05-15T10:05:01Z</timestamp>
    <source>planning</source>
    <type>session_view_response</type>
    <version>1.0</version>
    <correlation_id>corr-004</correlation_id>
  </header>
  <body>
    <request_message_id>req-001</request_message_id>
    <requested_session_id>sess-001</requested_session_id>
    <status>ok</status>
    <session_count>1</session_count>
    <sessions>
      <session>
        <session_id>sess-001</session_id>
        <title>Keynote: AI in Healthcare</title>
        <start_datetime>2026-05-15T14:00:00Z</start_datetime>
        <end_datetime>2026-05-15T15:00:00Z</end_datetime>
        <location>Aula A</location>
        <session_type>keynote</session_type>
        <status>published</status>
        <max_attendees>120</max_attendees>
        <current_attendees>25</current_attendees>
      </session>
    </sessions>
  </body>
</message>"""

VALID_CALENDAR_INVITE = b"""<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>msg-uuid</message_id>
    <timestamp>2026-05-15T09:00:00Z</timestamp>
    <source>frontend</source>
    <type>calendar.invite</type>
  </header>
  <body>
    <session_id>sess-001</session_id>
    <title>Keynote: AI in Healthcare</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
    <location>online</location>
  </body>
</message>"""


# ---------------------------------------------------------------------------
# Tests – valid messages
# ---------------------------------------------------------------------------

class TestValidMessages:
    def test_session_created_valid(self):
        valid, error = validate_xml(VALID_SESSION_CREATED, "session_created")
        assert valid is True
        assert error is None

    def test_session_updated_valid(self):
        valid, error = validate_xml(VALID_SESSION_UPDATED, "session_updated")
        assert valid is True
        assert error is None

    def test_session_deleted_valid(self):
        valid, error = validate_xml(VALID_SESSION_DELETED, "session_deleted")
        assert valid is True
        assert error is None

    def test_session_view_response_valid(self):
        valid, error = validate_xml(VALID_SESSION_VIEW_RESPONSE, "session_view_response")
        assert valid is True
        assert error is None

    def test_calendar_invite_valid(self):
        valid, error = validate_xml(VALID_CALENDAR_INVITE, "calendar.invite")
        assert valid is True
        assert error is None

    def test_accepts_string_input(self):
        """validate_xml accepts a plain str, not just bytes."""
        valid, error = validate_xml(VALID_SESSION_CREATED.decode(), "session_created")
        assert valid is True

    def test_session_created_optional_fields_absent(self):
        """session_created is valid without optional fields."""
        minimal = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_created</type>
          </header>
          <body>
            <session_id>sess-001</session_id>
            <title>Test</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
          </body>
        </message>"""
        valid, error = validate_xml(minimal, "session_created")
        assert valid is True

    def test_session_deleted_optional_fields_absent(self):
        """session_deleted is valid without reason and deleted_by."""
        minimal = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_deleted</type>
          </header>
          <body>
            <session_id>sess-001</session_id>
          </body>
        </message>"""
        valid, error = validate_xml(minimal, "session_deleted")
        assert valid is True

    def test_view_response_not_found_empty_sessions(self):
        """session_view_response with not_found status and empty sessions is valid."""
        xml = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_view_response</type>
          </header>
          <body>
            <request_message_id>req-001</request_message_id>
            <status>not_found</status>
            <session_count>0</session_count>
            <sessions/>
          </body>
        </message>"""
        valid, error = validate_xml(xml, "session_view_response")
        assert valid is True


# ---------------------------------------------------------------------------
# Tests – invalid messages
# ---------------------------------------------------------------------------

class TestInvalidMessages:
    def test_session_created_missing_session_id(self):
        """Missing required session_id in body must fail."""
        xml = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_created</type>
          </header>
          <body>
            <title>Test</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
          </body>
        </message>"""
        valid, error = validate_xml(xml, "session_created")
        assert valid is False
        assert error is not None

    def test_wrong_type_enum_value(self):
        """type field with an unrecognised value must fail."""
        xml = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_unknown</type>
          </header>
          <body>
            <session_id>sess-001</session_id>
            <title>Test</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
          </body>
        </message>"""
        valid, error = validate_xml(xml, "session_created")
        assert valid is False

    def test_view_response_invalid_status_enum(self):
        """status value not in {ok, not_found} must fail."""
        xml = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_view_response</type>
          </header>
          <body>
            <request_message_id>req-001</request_message_id>
            <status>error</status>
            <session_count>0</session_count>
            <sessions/>
          </body>
        </message>"""
        valid, error = validate_xml(xml, "session_view_response")
        assert valid is False

    def test_malformed_xml_returns_false(self):
        valid, error = validate_xml(b"<broken>", "session_created")
        assert valid is False
        assert error is not None

    def test_unknown_message_type(self):
        valid, error = validate_xml(b"<x/>", "totally_unknown_type")
        assert valid is False
        assert "No XSD schema registered" in error

    def test_calendar_invite_missing_namespace(self):
        """XML without the correct namespace must fail."""
        xml = b"""<message>
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>frontend</source>
            <type>calendar.invite</type>
          </header>
          <body>
            <session_id>sess-001</session_id>
            <title>Test</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
          </body>
        </message>"""
        valid, error = validate_xml(xml, "calendar.invite")
        assert valid is False

    def test_calendar_invite_invalid_datetime_format(self):
        """calendar.invite uses xs:dateTime — a plain date string must fail."""
        xml = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>frontend</source>
            <type>calendar.invite</type>
          </header>
          <body>
            <session_id>sess-001</session_id>
            <title>Test</title>
            <start_datetime>not-a-date</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
          </body>
        </message>"""
        valid, error = validate_xml(xml, "calendar.invite")
        assert valid is False


# ---------------------------------------------------------------------------
# Tests – validate_or_raise
# ---------------------------------------------------------------------------

class TestValidateOrRaise:
    def test_valid_does_not_raise(self):
        validate_or_raise(VALID_SESSION_CREATED, "session_created")

    def test_invalid_raises_value_error(self):
        xml = b"""<message xmlns="urn:integration:planning:v1">
          <header>
            <message_id>m1</message_id>
            <timestamp>2026-05-15T09:00:00Z</timestamp>
            <source>planning</source>
            <type>session_created</type>
          </header>
          <body>
            <title>Missing session_id</title>
            <start_datetime>2026-05-15T14:00:00Z</start_datetime>
            <end_datetime>2026-05-15T15:00:00Z</end_datetime>
          </body>
        </message>"""
        with pytest.raises(ValueError, match="XSD validation failed"):
            validate_or_raise(xml, "session_created")

    def test_unknown_type_raises_value_error(self):
        with pytest.raises(ValueError, match="XSD validation failed"):
            validate_or_raise(b"<x/>", "nonexistent_type")
