"""
Tests for graph_client.py.
All HTTP calls and MSAL token acquisition are mocked — no real network traffic.
"""

import pytest
from unittest.mock import MagicMock, patch
from graph_client import GraphClient, GraphClientError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CLIENT_ID = "test-client-id"
CLIENT_SECRET = "test-secret"
FAKE_TOKEN = "fake-access-token"
FAKE_ACCOUNT = {"username": "planning@test.onmicrosoft.com"}


@pytest.fixture
def client(mocker):
    """GraphClient with MSAL and token cache mocked out."""
    mocker.patch("graph_client._load_token_cache", return_value=MagicMock())
    mocker.patch("graph_client._save_token_cache")

    mock_msal = mocker.patch("graph_client.msal.ConfidentialClientApplication")
    mock_app = MagicMock()
    mock_app.get_accounts.return_value = [FAKE_ACCOUNT]
    mock_app.acquire_token_silent.return_value = {"access_token": FAKE_TOKEN}
    mock_msal.return_value = mock_app

    return GraphClient(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestGraphClientConstruction:
    def test_missing_credentials_raises(self, mocker):
        """GraphClient without credentials should raise GraphClientError."""
        mocker.patch("graph_client._load_token_cache", return_value=MagicMock())
        with pytest.raises(GraphClientError, match="credentials not configured"):
            GraphClient(client_id="", client_secret="")

    def test_valid_credentials_constructs(self, mocker):
        mocker.patch("graph_client._load_token_cache", return_value=MagicMock())
        mocker.patch("graph_client.msal.ConfidentialClientApplication")
        client = GraphClient(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)
        assert client._client_id == CLIENT_ID


# ---------------------------------------------------------------------------
# create_event
# ---------------------------------------------------------------------------

class TestCreateEvent:
    def test_create_event_success(self, client, mocker):
        """create_event returns the event ID from Graph API on success."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"id": "graph-event-001"}
        mocker.patch("graph_client.requests.post", return_value=mock_response)

        event_id = client.create_event(
            session_id="sess-001",
            title="Keynote",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="Aula A",
        )

        assert event_id == "graph-event-001"

    def test_create_event_sends_correct_payload(self, client, mocker):
        """create_event sends session_id as transactionId for idempotency."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"id": "evt-123"}
        mock_post = mocker.patch("graph_client.requests.post", return_value=mock_response)

        client.create_event(
            session_id="sess-idempotent",
            title="Test",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        payload = mock_post.call_args.kwargs["json"]
        assert payload["transactionId"] == "sess-idempotent"
        assert payload["subject"] == "Test"
        assert payload["start"]["timeZone"] == "UTC"

    def test_create_event_http_error_raises(self, client, mocker):
        """create_event raises GraphClientError on non-2xx response."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 403
        mock_response.json.return_value = {"error": {"message": "Access denied"}}
        mocker.patch("graph_client.requests.post", return_value=mock_response)

        with pytest.raises(GraphClientError, match="create_event"):
            client.create_event(
                session_id="sess-001",
                title="Test",
                start_datetime="2026-05-15T14:00:00Z",
                end_datetime="2026-05-15T15:00:00Z",
            )

    def test_create_event_location_omitted_when_empty(self, client, mocker):
        """create_event does not include location key when location is empty."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"id": "evt-001"}
        mock_post = mocker.patch("graph_client.requests.post", return_value=mock_response)

        client.create_event(
            session_id="s", title="t",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
            location="",
        )

        payload = mock_post.call_args.kwargs["json"]
        assert "location" not in payload


# ---------------------------------------------------------------------------
# update_event
# ---------------------------------------------------------------------------

class TestUpdateEvent:
    def test_update_event_success(self, client, mocker):
        """update_event succeeds on 2xx response."""
        mock_response = MagicMock()
        mock_response.ok = True
        mocker.patch("graph_client.requests.patch", return_value=mock_response)

        client.update_event(
            event_id="graph-event-001",
            title="Updated Title",
            start_datetime="2026-05-15T14:30:00Z",
            end_datetime="2026-05-15T15:30:00Z",
        )

    def test_update_event_http_error_raises(self, client, mocker):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 404
        mock_response.json.return_value = {"error": {"message": "Not found"}}
        mocker.patch("graph_client.requests.patch", return_value=mock_response)

        with pytest.raises(GraphClientError, match="update_event"):
            client.update_event(
                event_id="missing-event",
                title="X",
                start_datetime="2026-05-15T14:00:00Z",
                end_datetime="2026-05-15T15:00:00Z",
            )


# ---------------------------------------------------------------------------
# cancel_event
# ---------------------------------------------------------------------------

class TestCancelEvent:
    def test_cancel_event_success(self, client, mocker):
        """cancel_event succeeds on 2xx response."""
        mock_response = MagicMock()
        mock_response.ok = True
        mocker.patch("graph_client.requests.post", return_value=mock_response)

        client.cancel_event(event_id="graph-event-001", comment="Cancelled")

    def test_cancel_event_http_error_raises(self, client, mocker):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status_code = 500
        mock_response.json.return_value = {"error": {"message": "Server error"}}
        mocker.patch("graph_client.requests.post", return_value=mock_response)

        with pytest.raises(GraphClientError, match="cancel_event"):
            client.cancel_event(event_id="graph-event-001")


# ---------------------------------------------------------------------------
# Token acquisition
# ---------------------------------------------------------------------------

class TestTokenAcquisition:
    def test_uses_cached_token_when_available(self, mocker):
        """Silent token from cache is used — no interactive flow is triggered."""
        mocker.patch("graph_client._load_token_cache", return_value=MagicMock())
        mocker.patch("graph_client._save_token_cache")

        mock_msal = mocker.patch("graph_client.msal.ConfidentialClientApplication")
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = [FAKE_ACCOUNT]
        mock_app.acquire_token_silent.return_value = {"access_token": "cached-token"}
        mock_msal.return_value = mock_app

        client = GraphClient(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"id": "evt-1"}
        mocker.patch("graph_client.requests.post", return_value=mock_response)

        client.create_event(
            session_id="s", title="t",
            start_datetime="2026-05-15T14:00:00Z",
            end_datetime="2026-05-15T15:00:00Z",
        )

        mock_app.acquire_token_silent.assert_called_once()

    def test_no_cached_account_raises(self, mocker):
        """No cached accounts raises GraphClientError asking user to run auth_setup."""
        mocker.patch("graph_client._load_token_cache", return_value=MagicMock())
        mocker.patch("graph_client._save_token_cache")

        mock_msal = mocker.patch("graph_client.msal.ConfidentialClientApplication")
        mock_app = MagicMock()
        mock_app.get_accounts.return_value = []
        mock_msal.return_value = mock_app

        client = GraphClient(client_id=CLIENT_ID, client_secret=CLIENT_SECRET)

        with pytest.raises(GraphClientError, match="auth_setup.py"):
            client.create_event(
                session_id="s", title="t",
                start_datetime="2026-05-15T14:00:00Z",
                end_datetime="2026-05-15T15:00:00Z",
            )
