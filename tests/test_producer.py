"""
Tests for producer.py - message publishing to RabbitMQ.
"""

import pytest
from unittest.mock import patch, MagicMock
from producer import (
    publish_session_created,
    publish_session_updated,
    publish_session_deleted,
    publish_session_view_response,
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

    @patch("producer._publish_message")
    def test_publish_session_created_failure(self, mock_publish):
        """Publishing session_created should handle failure."""
        mock_publish.return_value = False

        result = publish_session_created(
            session_id="sess-001",
            title="Test Session",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Room A",
        )

        assert result is False

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

