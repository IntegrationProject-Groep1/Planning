"""
Tests for database service (calendar_service.py).
"""

import pytest
from unittest.mock import patch, MagicMock, call
import psycopg2
from calendar_service import (
    MessageLog,
    SessionService,
    SessionRegistrationService,
    UserService,
    IcsFeedService,
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
        """Deleting session should soft-delete (UPDATE, not DELETE)."""
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
    def test_get_session_not_found(self, mock_get_conn):
        """Getting a non-existent session should return None."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn

        result = SessionService.get("sess-unknown")

        assert result is None

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


class TestUserService:
    """Tests for user management (master_uuid + internal user_id)."""

    @patch("calendar_service._get_connection")
    def test_save_new_user(self, mock_get_conn):
        """Saving a new user should insert into users table."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_get_conn.return_value = mock_conn

        result = UserService.save(
            master_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
            email="jan@ehb.be",
        )

        assert result is True
        mock_cursor.execute.assert_called_once()
        assert "INSERT INTO users" in str(mock_cursor.execute.call_args)

    @patch("calendar_service._get_connection")
    def test_save_user_db_error_returns_false(self, mock_get_conn):
        """A DB error during save should return False."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.execute.side_effect = psycopg2.Error("connection error")
        mock_get_conn.return_value = mock_conn

        result = UserService.save(master_uuid="uuid-x", email="x@test.be")

        assert result is False

    @patch("calendar_service._get_connection")
    def test_get_by_master_uuid(self, mock_get_conn):
        """Looking up a user by master_uuid should return dict."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_row = {"master_uuid": "a1b2c3", "user_id": "uuid-internal", "email": "jan@ehb.be"}
        mock_cursor.fetchone.return_value = mock_row
        mock_get_conn.return_value = mock_conn

        result = UserService.get_by_master_uuid("a1b2c3")

        assert result == mock_row

    @patch("calendar_service._get_connection")
    def test_get_by_email(self, mock_get_conn):
        """Looking up a user by email should return dict."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_row = {"master_uuid": "a1b2c3", "email": "jan@ehb.be"}
        mock_cursor.fetchone.return_value = mock_row
        mock_get_conn.return_value = mock_conn

        result = UserService.get_by_email("jan@ehb.be")

        assert result == mock_row

    @patch("calendar_service._get_connection")
    def test_get_by_master_uuid_not_found(self, mock_get_conn):
        """Looking up an unknown master_uuid should return None."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn

        result = UserService.get_by_master_uuid("unknown-uuid")

        assert result is None


class TestSessionRegistrationService:
    """Tests for session registrations (user <-> session mapping)."""

    @patch("calendar_service._get_connection")
    def test_register_known_user(self, mock_get_conn):
        """Registering a known user should insert into session_registrations."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("internal-uuid-123",)
        mock_get_conn.return_value = mock_conn

        result = SessionRegistrationService.register(
            session_id="sess-001",
            master_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )

        assert result is True
        assert mock_cursor.execute.call_count == 3  # lookup + sessions insert + registrations insert

    @patch("calendar_service._get_connection")
    def test_register_unknown_user_returns_false(self, mock_get_conn):
        """Registering an unknown master_uuid should return False without writing."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None  # user not found
        mock_get_conn.return_value = mock_conn

        result = SessionRegistrationService.register(
            session_id="sess-001",
            master_uuid="unknown-uuid",
        )

        assert result is False
        assert mock_cursor.execute.call_count == 1  # only the lookup

    @patch("calendar_service._get_connection")
    def test_cancel_known_user(self, mock_get_conn):
        """Cancelling a known user's registration should update status."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("internal-uuid-123",)
        mock_get_conn.return_value = mock_conn

        result = SessionRegistrationService.cancel(
            session_id="sess-001",
            master_uuid="a1b2c3d4-e5f6-7890-abcd-ef1234567890",
        )

        assert result is True
        assert "UPDATE session_registrations" in str(mock_cursor.execute.call_args)

    @patch("calendar_service._get_connection")
    def test_cancel_unknown_user_returns_false(self, mock_get_conn):
        """Cancelling an unknown master_uuid should return False."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        mock_get_conn.return_value = mock_conn

        result = SessionRegistrationService.cancel(
            session_id="sess-001",
            master_uuid="unknown-uuid",
        )

        assert result is False

    @patch("calendar_service._get_connection")
    def test_list_for_session(self, mock_get_conn):
        """Listing registrations should return list with user details."""
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_rows = [
            {"session_id": "sess-001", "user_id": "uuid-1", "master_uuid": "m-uuid-1", "email": "a@test.be", "status": "confirmed"},
            {"session_id": "sess-001", "user_id": "uuid-2", "master_uuid": "m-uuid-2", "email": "b@test.be", "status": "confirmed"},
        ]
        mock_cursor.fetchall.return_value = mock_rows
        mock_get_conn.return_value = mock_conn

        result = SessionRegistrationService.list_for_session("sess-001")

        assert len(result) == 2
        assert result[0]["email"] == "a@test.be"
