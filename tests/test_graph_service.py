"""
Tests for graph_service.py.
GraphClient and DB calls are mocked — no real network or database traffic.
"""

import pytest
from unittest.mock import MagicMock, patch
from graph_service import GraphService
from graph_client import GraphClientError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_graph_client(mocker, event_id="graph-event-001"):
    """Return a mock GraphClient whose create_event returns event_id."""
    mock_client = MagicMock()
    mock_client.create_event.return_value = event_id
    mocker.patch("graph_service._build_client", return_value=mock_client)
    return mock_client


# ---------------------------------------------------------------------------
# sync_created
# ---------------------------------------------------------------------------

class TestSyncCreated:
    def test_creates_event_and_persists_sync(self, mocker):
        """sync_created calls create_event and upserts a sync record."""
        mock_client = _make_graph_client(mocker, "evt-001")
        mock_upsert = mocker.patch("graph_service._upsert_sync")
        mocker.patch("graph_service._mark_sync_failed")

        result = GraphService.sync_created(
            session_id="sess-001",
            title="Keynote",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Aula A",
        )

        assert result is True
        mock_client.create_event.assert_called_once_with(
            session_id="sess-001",
            title="Keynote",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Aula A",
        )
        mock_upsert.assert_called_once_with("sess-001", "evt-001", status="synced")

    def test_graph_api_failure_marks_sync_failed(self, mocker):
        """sync_created returns False and records failure when Graph API fails."""
        mock_client = MagicMock()
        mock_client.create_event.side_effect = GraphClientError("403 Forbidden")
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mock_fail = mocker.patch("graph_service._mark_sync_failed")

        result = GraphService.sync_created(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        assert result is False
        mock_fail.assert_called_once_with("sess-001", "403 Forbidden")

    def test_returns_false_when_graph_not_configured(self, mocker):
        """sync_created returns False gracefully when credentials are absent."""
        mocker.patch("graph_service._build_client", return_value=None)

        result = GraphService.sync_created(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        assert result is False

    def test_unexpected_exception_marks_sync_failed(self, mocker):
        """Unexpected exceptions in sync_created are caught and recorded."""
        mock_client = MagicMock()
        mock_client.create_event.side_effect = RuntimeError("DB down")
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mock_fail = mocker.patch("graph_service._mark_sync_failed")

        result = GraphService.sync_created(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        assert result is False
        mock_fail.assert_called_once()


# ---------------------------------------------------------------------------
# sync_updated
# ---------------------------------------------------------------------------

class TestSyncUpdated:
    def test_updates_existing_event(self, mocker):
        """sync_updated calls update_event when a synced event exists."""
        mock_client = MagicMock()
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mocker.patch("graph_service._get_event_id", return_value="evt-001")
        mock_upsert = mocker.patch("graph_service._upsert_sync")

        result = GraphService.sync_updated(
            session_id="sess-001",
            title="Updated Title",
            start_datetime="2026-05-15T14:30:00Z",
            end_datetime="2026-05-15T15:30:00Z",
            location="Room B",
        )

        assert result is True
        mock_client.update_event.assert_called_once_with(
            event_id="evt-001",
            title="Updated Title",
            start_datetime="2026-05-15T14:30:00Z",
            end_datetime="2026-05-15T15:30:00Z",
            location="Room B",
        )
        mock_upsert.assert_called_once_with("sess-001", "evt-001", status="synced")

    def test_falls_back_to_create_when_no_event_found(self, mocker):
        """sync_updated falls back to sync_created when no event exists in DB."""
        mock_client = MagicMock()
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mocker.patch("graph_service._get_event_id", return_value=None)
        mock_sync_created = mocker.patch.object(
            GraphService, "sync_created", return_value=True
        )

        result = GraphService.sync_updated(
            session_id="sess-new",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        assert result is True
        mock_sync_created.assert_called_once()

    def test_graph_api_failure_marks_sync_failed(self, mocker):
        mock_client = MagicMock()
        mock_client.update_event.side_effect = GraphClientError("500 error")
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mocker.patch("graph_service._get_event_id", return_value="evt-001")
        mock_fail = mocker.patch("graph_service._mark_sync_failed")

        result = GraphService.sync_updated(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        assert result is False
        mock_fail.assert_called_once_with("sess-001", "500 error")

    def test_returns_false_when_graph_not_configured(self, mocker):
        mocker.patch("graph_service._build_client", return_value=None)

        result = GraphService.sync_updated(
            session_id="sess-001",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        assert result is False


# ---------------------------------------------------------------------------
# sync_deleted
# ---------------------------------------------------------------------------

class TestSyncDeleted:
    def test_cancels_existing_event(self, mocker):
        """sync_deleted calls cancel_event and marks sync as deleted."""
        mock_client = MagicMock()
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mocker.patch("graph_service._get_event_id", return_value="evt-001")
        mock_mark_deleted = mocker.patch("graph_service._mark_sync_deleted")

        result = GraphService.sync_deleted(
            session_id="sess-001",
            reason="Session cancelled by admin",
        )

        assert result is True
        mock_client.cancel_event.assert_called_once_with(
            event_id="evt-001",
            comment="Session cancelled by admin",
        )
        mock_mark_deleted.assert_called_once_with("sess-001")

    def test_no_op_when_no_event_found(self, mocker):
        """sync_deleted is a no-op (returns True) when no event exists."""
        mock_client = MagicMock()
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mocker.patch("graph_service._get_event_id", return_value=None)

        result = GraphService.sync_deleted(session_id="sess-no-event")

        assert result is True
        mock_client.cancel_event.assert_not_called()

    def test_graph_api_failure_marks_sync_failed(self, mocker):
        mock_client = MagicMock()
        mock_client.cancel_event.side_effect = GraphClientError("403 error")
        mocker.patch("graph_service._build_client", return_value=mock_client)
        mocker.patch("graph_service._get_event_id", return_value="evt-001")
        mock_fail = mocker.patch("graph_service._mark_sync_failed")

        result = GraphService.sync_deleted(session_id="sess-001")

        assert result is False
        mock_fail.assert_called_once_with("sess-001", "403 error")

    def test_returns_false_when_graph_not_configured(self, mocker):
        mocker.patch("graph_service._build_client", return_value=None)

        result = GraphService.sync_deleted(session_id="sess-001")

        assert result is False


# ---------------------------------------------------------------------------
# Consumer integration: Graph calls do not affect message ACK
# ---------------------------------------------------------------------------

class TestConsumerGraphIntegration:
    """
    Verify that a Graph API failure inside a consumer handler does not
    cause the message to be nacked (DB persistence still succeeds).
    """

    def test_calendar_invite_handler_acks_even_when_graph_fails(self, mocker):
        """Handle calendar.invite ACKs the message even if Graph sync fails."""
        from consumer import handle_calendar_invite
        from xml_models import CalendarInviteMessage, CalendarInviteBody, MessageHeader

        msg = CalendarInviteMessage(
            header=MessageHeader(
                message_id="msg-001",
                timestamp="2026-05-15T09:00:00Z",
                source="frontend",
                type="calendar.invite",
            ),
            body=CalendarInviteBody(
                session_id="sess-001",
                title="Keynote",
                start_datetime="2026-05-15T14:00:00Z",
                end_datetime="2026-05-15T15:00:00Z",
                location="online",
            ),
        )

        mocker.patch("consumer.MessageLog.log_message", return_value=True)
        mocker.patch("consumer.SessionService.create_or_update")
        mocker.patch("consumer.CalendarInviteService.create")
        mocker.patch("consumer.MessageLog.update_message_status")
        # Graph API fails
        mocker.patch("consumer.GraphService.sync_created", return_value=False)

        mock_channel = MagicMock()
        handle_calendar_invite(msg, mock_channel, delivery_tag=1)

        # Message must still be ACKed
        mock_channel.basic_ack.assert_called_once_with(delivery_tag=1)
        mock_channel.basic_nack.assert_not_called()
