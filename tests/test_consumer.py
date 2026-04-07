"""
Tests for consumer.py - message consumption and handling.
"""

import pytest
from unittest.mock import patch, MagicMock
from xml_models import CalendarInviteMessage, CalendarInviteBody, MessageHeader
from xml_handlers import parse_calendar_invite
from consumer import (
    handle_calendar_invite,
    handle_session_created,
    handle_session_deleted,
    route_message,
)


@pytest.fixture
def mock_channel():
    """Mock RabbitMQ channel."""
    mock = MagicMock()
    return mock


@pytest.fixture
def sample_calendar_invite_message():
    """Sample parsed calendar invite message."""
    return CalendarInviteMessage(
        header=MessageHeader(
            message_id="msg-test-001",
            timestamp="2026-05-15T09:00:00Z",
            source="calendar",
            type="calendar.invite",
        ),
        body=CalendarInviteBody(
            session_id="sess-test-001",
            title="Test Session",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Room A",
        ),
    )


class TestHandleCalendarInvite:
    """Tests for calendar.invite message handler."""

    @patch("consumer.MessageLog.log_message")
    @patch("consumer.SessionService.create_or_update")
    @patch("consumer.CalendarInviteService.create")
    @patch("consumer.MessageLog.update_message_status")
    def test_handle_calendar_invite_success(
        self, mock_update_status, mock_create_invite, mock_create_session, mock_log_msg, 
        sample_calendar_invite_message, mock_channel
    ):
        """Handling valid calendar.invite should succeed."""
        mock_log_msg.return_value = True
        mock_create_session.return_value = True
        mock_create_invite.return_value = True

        handle_calendar_invite(sample_calendar_invite_message, mock_channel, 123)

        # Should log message for idempotency
        mock_log_msg.assert_called_once()
        assert "calendar.invite" in str(mock_log_msg.call_args)

        # Should create/update session
        mock_create_session.assert_called_once()
        assert "sess-test-001" in str(mock_create_session.call_args)

        # Should create calendar invite record
        mock_create_invite.assert_called_once()

        # Should ack the message
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=123)

    @patch("consumer.MessageLog.log_message")
    def test_handle_calendar_invite_duplicate(
        self, mock_log_msg, sample_calendar_invite_message, mock_channel
    ):
        """Handling duplicate calendar.invite should not process again."""
        mock_log_msg.return_value = False  # Duplicate

        handle_calendar_invite(sample_calendar_invite_message, mock_channel, 123)

        # Should still ack the message
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=123)

        # Should not nack
        mock_channel.basic_nack.assert_not_called()

    @patch("consumer.MessageLog.log_message")
    @patch("consumer.SessionService.create_or_update")
    @patch("consumer.CalendarInviteService.create")
    @patch("consumer.MessageLog.update_message_status")
    def test_handle_calendar_invite_error_handling(
        self, mock_update_status, mock_create_invite, mock_create_session, mock_log_msg,
        sample_calendar_invite_message, mock_channel
    ):
        """Handling error should nack and log failure."""
        mock_log_msg.return_value = True
        mock_create_session.side_effect = Exception("DB error")

        handle_calendar_invite(sample_calendar_invite_message, mock_channel, 123)

        # Should log failure
        mock_update_status.assert_called()
        assert "failed" in str(mock_update_status.call_args)

        # Should nack with no requeue
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=123, requeue=False)


class TestHandleSessionCreated:
    """Tests for session_created message handler."""

    @patch("consumer.MessageLog.log_message")
    @patch("consumer.SessionService.create_or_update")
    @patch("consumer.SessionEventService.log_event")
    @patch("consumer.MessageLog.update_message_status")
    def test_handle_session_created_success(
        self, mock_update_status, mock_log_event, mock_create_session, mock_log_msg,
        sample_session_created_xml, mock_channel
    ):
        """Handling valid session_created should succeed."""
        from xml_handlers import parse_session_created
        msg = parse_session_created(sample_session_created_xml)
        
        mock_log_msg.return_value = True
        mock_create_session.return_value = True
        mock_log_event.return_value = True

        handle_session_created(msg, mock_channel, 456)

        mock_log_msg.assert_called_once()
        mock_create_session.assert_called_once()
        mock_log_event.assert_called_once()
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=456)


class TestRouteMessage:
    """Tests for message routing."""

    @patch("consumer.handle_calendar_invite")
    def test_route_calendar_invite_message(
        self, mock_handle, sample_calendar_invite_message, mock_channel
    ):
        """Routing should dispatch to calendar.invite handler."""
        route_message(sample_calendar_invite_message, mock_channel, 1)
        mock_handle.assert_called_once()

    def test_route_unknown_message_type(self, mock_channel):
        """Routing unknown message type should nack."""
        unknown_msg = "unknown"
        route_message(unknown_msg, mock_channel, 1)
        mock_channel.basic_nack.assert_called_once_with(delivery_tag=1, requeue=False)
