"""
Tests for producer.py - message publishing to RabbitMQ.
"""

import pytest
from unittest.mock import patch, MagicMock, call
from producer import (
    publish_session_created,
    publish_session_updated,
    publish_session_deleted,
    publish_session_view_response,
    _publish_with_validation_and_retry,
)


class TestPublishSessionCreated:
    """Tests for publish_session_created."""

    @patch("producer._publish_message")
    def test_publish_session_created_success(self, mock_publish):
        """Publishing session_created should succeed."""
        mock_publish.return_value = True

        result = publish_session_created(
            session_id="sess-001",
            title="Test Session",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Room A",
        )

        assert result is True
        assert mock_publish.called
        assert "planning.session.created" in str(mock_publish.call_args)

    @patch("producer.time.sleep")
    @patch("producer._publish_message")
    def test_publish_session_created_failure(self, mock_publish, mock_sleep):
        """Publishing session_created should return False after all retries fail."""
        mock_publish.return_value = False

        result = publish_session_created(
            session_id="sess-001",
            title="Test Session",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Room A",
        )

        assert result is False
        # Default max_retries=3 means _publish_message is called 3 times
        assert mock_publish.call_count == 3

    @patch("producer._publish_message")
    def test_publish_session_created_with_correlation_id(self, mock_publish):
        """Publishing with correlation_id should pass it through."""
        mock_publish.return_value = True

        publish_session_created(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Room A",
            correlation_id="corr-123",
        )

        # Verify the XML contains correlation_id
        call_args = mock_publish.call_args[0][0]  # First positional arg is XML
        assert "corr-123" in call_args


class TestPublishSessionUpdated:
    """Tests for publish_session_updated."""

    @patch("producer._publish_message")
    def test_publish_session_updated_success(self, mock_publish):
        """Publishing session_updated should succeed."""
        mock_publish.return_value = True

        result = publish_session_updated(
            session_id="sess-001",
            title="Updated Title",
            start_datetime="2026-05-15T14:30:00Z",
            end_datetime="2026-05-15T15:30:00Z",
            location="Room B",
            current_attendees=25,
        )

        assert result is True
        assert mock_publish.called
        assert "planning.session.updated" in str(mock_publish.call_args)


class TestPublishSessionDeleted:
    """Tests for publish_session_deleted."""

    @patch("producer._publish_message")
    def test_publish_session_deleted_success(self, mock_publish):
        """Publishing session_deleted should succeed."""
        mock_publish.return_value = True

        result = publish_session_deleted(
            session_id="sess-001",
            reason="cancelled",
            deleted_by="admin",
        )

        assert result is True
        assert mock_publish.called
        assert "planning.session.deleted" in str(mock_publish.call_args)

    @patch("producer._publish_message")
    def test_publish_session_deleted_includes_reason(self, mock_publish):
        """Published message should include deletion reason."""
        mock_publish.return_value = True

        publish_session_deleted(
            session_id="sess-001",
            reason="cancelled",
            deleted_by="admin",
        )

        call_args = mock_publish.call_args[0][0]
        assert "cancelled" in call_args
        assert "admin" in call_args


class TestPublishSessionViewResponse:
    """Tests for publish_session_view_response."""

    @patch("producer._publish_message")
    def test_publish_session_view_response_success(self, mock_publish):
        """Publishing session_view_response should succeed."""
        mock_publish.return_value = True

        result = publish_session_view_response(
            request_message_id="req-001",
            requested_session_id="sess-001",
            status="ok",
            sessions=[
                {
                    "session_id": "sess-001",
                    "title": "Test",
                    "start_datetime": "2026-05-15T14:00:00Z",
                    "end_datetime": "2026-05-15T15:00:00Z",
                }
            ],
        )

        assert result is True
        assert mock_publish.called
        assert "planning.session.view_response" in str(mock_publish.call_args)

    @patch("producer._publish_message")
    def test_publish_session_view_response_not_found(self, mock_publish):
        """Publishing response with not_found status should work."""
        mock_publish.return_value = True

        result = publish_session_view_response(
            request_message_id="req-001",
            requested_session_id="sess-notfound",
            status="not_found",
            sessions=[],
        )

        assert result is True
        call_args = mock_publish.call_args[0][0]
        assert "not_found" in call_args

    @patch("producer._publish_message")
    def test_publish_session_view_response_multiple_sessions(self, mock_publish):
        """Publishing response with multiple sessions should work."""
        mock_publish.return_value = True

        sessions = [
            {
                "session_id": "sess-001",
                "title": "Session 1",
                "start_datetime": "2026-05-15T14:00:00Z",
                "end_datetime": "2026-05-15T15:00:00Z",
            },
            {
                "session_id": "sess-002",
                "title": "Session 2",
                "start_datetime": "2026-05-15T15:00:00Z",
                "end_datetime": "2026-05-15T16:00:00Z",
            },
        ]

        publish_session_view_response(
            request_message_id="req-001",
            requested_session_id=None,
            status="ok",
            sessions=sessions,
        )

        call_args = mock_publish.call_args[0][0]
        assert "<session_count>2</session_count>" in call_args
        assert "sess-001" in call_args
        assert "sess-002" in call_args


# ============================================================================
# Tests for XSD validation gate in _publish_with_validation_and_retry
# ============================================================================

VALID_SESSION_CREATED_XML = b"""<message xmlns="urn:integration:planning:v1">
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

INVALID_SESSION_CREATED_XML = b"""<message xmlns="urn:integration:planning:v1">
  <header>
    <message_id>m1</message_id>
    <timestamp>2026-05-15T09:00:00Z</timestamp>
    <source>planning</source>
    <type>session_created</type>
  </header>
  <body>
    <title>Missing required session_id</title>
    <start_datetime>2026-05-15T14:00:00Z</start_datetime>
    <end_datetime>2026-05-15T15:00:00Z</end_datetime>
  </body>
</message>"""


class TestPublishWithValidationAndRetry:
    """Tests for _publish_with_validation_and_retry."""

    @patch("producer._publish_message")
    def test_valid_xml_is_published(self, mock_publish):
        """Valid XML passes XSD gate and reaches RabbitMQ."""
        mock_publish.return_value = True

        result = _publish_with_validation_and_retry(
            VALID_SESSION_CREATED_XML.decode(),
            "planning.session.created",
            "session_created",
        )

        assert result is True
        assert mock_publish.call_count == 1

    @patch("producer._publish_message")
    def test_invalid_xml_is_blocked(self, mock_publish):
        """Invalid XML is blocked at the XSD gate — never reaches RabbitMQ."""
        result = _publish_with_validation_and_retry(
            INVALID_SESSION_CREATED_XML.decode(),
            "planning.session.created",
            "session_created",
        )

        assert result is False
        mock_publish.assert_not_called()

    @patch("producer.time.sleep")
    @patch("producer._publish_message")
    def test_retries_on_publish_failure(self, mock_publish, mock_sleep):
        """Failed publish is retried up to max_retries times."""
        mock_publish.return_value = False

        result = _publish_with_validation_and_retry(
            VALID_SESSION_CREATED_XML.decode(),
            "planning.session.created",
            "session_created",
            max_retries=3,
        )

        assert result is False
        assert mock_publish.call_count == 3

    @patch("producer.time.sleep")
    @patch("producer._publish_message")
    def test_succeeds_on_second_attempt(self, mock_publish, mock_sleep):
        """Publish succeeds on the second attempt after one failure."""
        mock_publish.side_effect = [False, True]

        result = _publish_with_validation_and_retry(
            VALID_SESSION_CREATED_XML.decode(),
            "planning.session.created",
            "session_created",
            max_retries=3,
        )

        assert result is True
        assert mock_publish.call_count == 2

    @patch("producer.time.sleep")
    @patch("producer._publish_message")
    def test_exponential_backoff_delays(self, mock_publish, mock_sleep):
        """Sleep durations follow exponential backoff: 1s, 2s."""
        mock_publish.return_value = False

        _publish_with_validation_and_retry(
            VALID_SESSION_CREATED_XML.decode(),
            "planning.session.created",
            "session_created",
            max_retries=3,
            initial_delay=1.0,
        )

        # 2 sleeps between 3 attempts: 1.0s then 2.0s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)
        mock_sleep.assert_any_call(2.0)

    @patch("producer._publish_message")
    def test_unknown_message_type_blocked(self, mock_publish):
        """Unknown message type cannot pass XSD gate."""
        result = _publish_with_validation_and_retry(
            b"<x/>",
            "planning.some.queue",
            "totally_unknown",
        )

        assert result is False
        mock_publish.assert_not_called()
