"""
Tests for database service (calendar_service.py).
"""

import pytest
from unittest.mock import patch, MagicMock
from calendar_service import (
    MessageLog,
    SessionService,
    CalendarInviteService,
    SessionEventService,
    SessionViewRequestService,
    MessageStatus,
)


class TestMessageLog:
    """Tests for message logging and idempotency."""

    @patch("calendar_service._get_connection")
    def test_log_message_new_returns_true(self, mock_get_conn):
        """Logging a new message should return True."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = MessageLog.log_message(
            message_id="msg-001",
            message_type="calendar.invite",
            source="calendar",
            timestamp="2026-05-15T09:00:00Z",
        )

        assert result is True
        mock_cursor.execute.assert_called_once()
        mock_conn.commit.assert_called_once()

    @patch("calendar_service._get_connection")
    def test_log_message_duplicate_returns_false(self, mock_get_conn):
        """Logging a duplicate message should return False."""
        import psycopg2

        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.IntegrityError("Key already exists", None, None)
        mock_get_conn.return_value = mock_conn

        result = MessageLog.log_message(
            message_id="msg-001",
            message_type="calendar.invite",
            source="calendar",
            timestamp="2026-05-15T09:00:00Z",
        )

        assert result is False

    @patch("calendar_service._get_connection")
    def test_update_message_status(self, mock_get_conn):
        """Updating message status should execute update query."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = MessageLog.update_message_status(
            message_id="msg-001",
            status="processed",
        )

        assert result is True
        mock_cursor.execute.assert_called_once()
        assert "UPDATE message_log" in str(mock_cursor.execute.call_args)

    @patch("calendar_service._get_connection")
    def test_get_message(self, mock_get_conn):
        """Getting a message should return dict."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_row = {"message_id": "msg-001", "status": "processed"}
        mock_cursor.fetchone.return_value = mock_row
        mock_get_conn.return_value = mock_conn

        result = MessageLog.get_message("msg-001")

        assert result == mock_row
        mock_cursor.execute.assert_called_once_with(
            "SELECT * FROM message_log WHERE message_id = %s",
            ("msg-001",),
        )


class TestSessionService:
    """Tests for session management."""

    @patch("calendar_service._get_connection")
    def test_create_or_update_session(self, mock_get_conn, sample_session_data):
        """Creating/updating session should execute insert query."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = SessionService.create_or_update(**sample_session_data)

        assert result is True
        mock_cursor.execute.assert_called_once()
        assert "INSERT INTO sessions" in str(mock_cursor.execute.call_args)

    @patch("calendar_service._get_connection")
    def test_delete_session(self, mock_get_conn):
        """Deleting session should update status."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = SessionService.delete("sess-001")

        assert result is True
        mock_cursor.execute.assert_called_once()
        assert "UPDATE sessions" in str(mock_cursor.execute.call_args)

    @patch("calendar_service._get_connection")
    def test_get_session(self, mock_get_conn):
        """Getting session should return dict."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_row = {"session_id": "sess-001", "title": "Test"}
        mock_cursor.fetchone.return_value = mock_row
        mock_get_conn.return_value = mock_conn

        result = SessionService.get("sess-001")

        assert result == mock_row

    @patch("calendar_service._get_connection")
    def test_list_all_sessions(self, mock_get_conn):
        """Listing sessions should return list of dicts."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_rows = [
            {"session_id": "sess-001", "title": "Test 1"},
            {"session_id": "sess-002", "title": "Test 2"},
        ]
        mock_cursor.fetchall.return_value = mock_rows
        mock_get_conn.return_value = mock_conn

        result = SessionService.list_all(limit=10)

        assert len(result) == 2
        assert result[0]["session_id"] == "sess-001"


class TestCalendarInviteService:
    """Tests for calendar invite management."""

    @patch("calendar_service._get_connection")
    def test_create_calendar_invite(self, mock_get_conn, sample_calendar_invite_data):
        """Creating calendar invite should execute insert query."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = CalendarInviteService.create(**sample_calendar_invite_data)

        assert result is True
        assert mock_cursor.execute.called

    @patch("calendar_service._get_connection")
    def test_get_calendar_invite(self, mock_get_conn):
        """Getting calendar invite should return dict."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_row = {"message_id": "msg-001", "session_id": "sess-001"}
        mock_cursor.fetchone.return_value = mock_row
        mock_get_conn.return_value = mock_conn

        result = CalendarInviteService.get("msg-001")

        assert result == mock_row

    @patch("calendar_service._get_connection")
    def test_list_calendar_invites(self, mock_get_conn):
        """Listing invites should return list."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_rows = [
            {"message_id": "msg-001", "session_id": "sess-001"},
            {"message_id": "msg-002", "session_id": "sess-002"},
        ]
        mock_cursor.fetchall.return_value = mock_rows
        mock_get_conn.return_value = mock_conn

        result = CalendarInviteService.list_all(limit=10)

        assert len(result) == 2

    @patch("calendar_service._get_connection")
    def test_update_status(self, mock_get_conn):
        """Updating invite status should succeed."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = CalendarInviteService.update_status("msg-001", "processed")

        assert result is True
        mock_cursor.execute.assert_called_once()


class TestSessionEventService:
    """Tests for session event logging."""

    @patch("calendar_service._get_connection")
    def test_log_event(self, mock_get_conn):
        """Logging event should execute insert query."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = SessionEventService.log_event(
            message_id="msg-001",
            timestamp="2026-05-15T09:00:00Z",
            source="planning",
            event_type="session_created",
            session_id="sess-001",
        )

        assert result is True
        mock_cursor.execute.assert_called_once()

    @patch("calendar_service._get_connection")
    def test_list_for_session(self, mock_get_conn):
        """Listing events for session should return list."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_rows = [
            {"message_id": "msg-001", "type": "session_created"},
            {"message_id": "msg-002", "type": "session_updated"},
        ]
        mock_cursor.fetchall.return_value = mock_rows
        mock_get_conn.return_value = mock_conn

        result = SessionEventService.list_for_session("sess-001", limit=10)

        assert len(result) == 2


class TestSessionViewRequestService:
    """Tests for session view request tracking."""

    @patch("calendar_service._get_connection")
    def test_log_request(self, mock_get_conn):
        """Logging view request should succeed."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = SessionViewRequestService.log_request(
            message_id="req-001",
            timestamp="2026-05-15T10:00:00Z",
            source="calendar",
            session_id="sess-001",
        )

        assert result is True
        mock_cursor.execute.assert_called_once()

    @patch("calendar_service._get_connection")
    def test_mark_responded(self, mock_get_conn):
        """Marking request as responded should succeed."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = SessionViewRequestService.mark_responded(1, status="ok")

        assert result is True
        mock_cursor.execute.assert_called_once()

    @patch("calendar_service._get_connection")
    def test_get_pending(self, mock_get_conn):
        """Getting pending requests should return list."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_rows = [
            {"request_id": 1, "message_id": "req-001", "session_id": "sess-001"},
        ]
        mock_cursor.fetchall.return_value = mock_rows
        mock_get_conn.return_value = mock_conn

        result = SessionViewRequestService.get_pending()

        assert len(result) == 1
        assert result[0]["request_id"] == 1
