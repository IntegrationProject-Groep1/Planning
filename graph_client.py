"""
Microsoft Graph API client for Outlook calendar management.

Authentication uses the OAuth2 delegated (authorization code) flow.
Run auth_setup.py once to authenticate and persist the token cache.
The service then uses the cached refresh token automatically.

Required environment variables:
    AZURE_CLIENT_ID      – App registration client ID
    AZURE_CLIENT_SECRET  – App registration client secret
    TOKEN_CACHE_FILE     – Path to the MSAL token cache JSON file
                           (default: token_cache.json)
"""

import logging
import os
from typing import Optional

import msal
import requests

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
_AUTHORITY = "https://login.microsoftonline.com/common"
_SCOPES = ["User.Read", "Calendars.ReadWrite"]

_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
_TOKEN_CACHE_FILE = os.getenv("TOKEN_CACHE_FILE", "token_cache.json")


class GraphClientError(Exception):
    """Raised when a Graph API call fails."""


def _load_token_cache(cache_file: str) -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if os.path.exists(cache_file):
        with open(cache_file) as f:
            cache.deserialize(f.read())
    return cache


def _save_token_cache(cache: msal.SerializableTokenCache, cache_file: str) -> None:
    if cache.has_state_changed:
        with open(cache_file, "w") as f:
            f.write(cache.serialize())


class GraphClient:
    """
    Thin wrapper around Microsoft Graph API for Outlook calendar events.

    Two authentication modes:
      1. Per-user token (preferred): pass ``access_token`` directly.
         TokenService resolves and refreshes these before calling this class.
      2. Shared service account (legacy): tokens are read from the MSAL
         file cache produced by auth_setup.py.
    """

    def __init__(
        self,
        client_id: str = "",
        client_secret: str = "",
        cache_file: str = "",
        access_token: str = "",
    ):
        self._access_token = access_token  # per-user token, may be empty

        if not access_token:
            # Fall back to the shared MSAL file-cache flow
            self._client_id = client_id or _CLIENT_ID
            self._client_secret = client_secret or _CLIENT_SECRET
            self._cache_file = cache_file or _TOKEN_CACHE_FILE

            if not all([self._client_id, self._client_secret]):
                raise GraphClientError(
                    "Graph API credentials not configured. "
                    "Set AZURE_CLIENT_ID and AZURE_CLIENT_SECRET."
                )

            self._cache = _load_token_cache(self._cache_file)
            self._msal_app = msal.ConfidentialClientApplication(
                self._client_id,
                authority=_AUTHORITY,
                client_credential=self._client_secret,
                token_cache=self._cache,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Return the access token — either the injected per-user token or
        one acquired silently from the shared MSAL file cache."""
        if self._access_token:
            return self._access_token

        accounts = self._msal_app.get_accounts()
        result = None
        if accounts:
            result = self._msal_app.acquire_token_silent(_SCOPES, account=accounts[0])
        _save_token_cache(self._cache, self._cache_file)
        if not result or "access_token" not in result:
            raise GraphClientError(
                "No valid token found. Run auth_setup.py to authenticate first."
            )
        return result["access_token"]

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _events_url(event_id: Optional[str] = None) -> str:
        base = f"{GRAPH_BASE_URL}/me/calendar/events"
        return f"{base}/{event_id}" if event_id else base

    @staticmethod
    def _raise_for_status(response: requests.Response, context: str) -> None:
        """Raise GraphClientError with a structured message on HTTP errors."""
        if not response.ok:
            try:
                detail = response.json().get("error", {}).get("message", response.text)
            except Exception:
                detail = response.text
            raise GraphClientError(
                f"{context} failed | status={response.status_code} | detail={detail}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def create_event(
        self,
        session_id: str,
        title: str,
        start_datetime: str,
        end_datetime: str,
        location: str = "",
    ) -> str:
        """
        Create an Outlook calendar event for the given session.

        Args:
            session_id:      Used as the transactionId for idempotency.
            title:           Event subject.
            start_datetime:  ISO 8601 UTC string (e.g. "2026-05-15T14:00:00Z").
            end_datetime:    ISO 8601 UTC string.
            location:        Display name of the location (optional).

        Returns:
            The Graph API event ID (str) of the newly created event.

        Raises:
            GraphClientError on failure.
        """
        payload = {
            "subject": title,
            "start": {"dateTime": start_datetime, "timeZone": "UTC"},
            "end": {"dateTime": end_datetime, "timeZone": "UTC"},
            "transactionId": session_id,  # idempotency key
        }
        if location:
            payload["location"] = {"displayName": location}

        response = requests.post(
            self._events_url(),
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        self._raise_for_status(response, f"create_event(session_id={session_id})")

        event_id: str = response.json()["id"]
        logger.info(
            "Outlook event created | session_id=%s | event_id=%s",
            session_id,
            event_id,
        )
        return event_id

    def update_event(
        self,
        event_id: str,
        title: str,
        start_datetime: str,
        end_datetime: str,
        location: str = "",
    ) -> None:
        """
        Update an existing Outlook calendar event.

        Args:
            event_id:       Graph API event ID.
            title:          New event subject.
            start_datetime: ISO 8601 UTC string.
            end_datetime:   ISO 8601 UTC string.
            location:       New location display name (optional).

        Raises:
            GraphClientError on failure.
        """
        payload: dict = {
            "subject": title,
            "start": {"dateTime": start_datetime, "timeZone": "UTC"},
            "end": {"dateTime": end_datetime, "timeZone": "UTC"},
        }
        if location:
            payload["location"] = {"displayName": location}

        response = requests.patch(
            self._events_url(event_id) + "?sendUpdates=all",
            json=payload,
            headers=self._headers(),
            timeout=15,
        )
        self._raise_for_status(response, f"update_event(event_id={event_id})")
        logger.info("Outlook event updated | event_id=%s", event_id)

    def cancel_event(self, event_id: str, comment: str = "Session cancelled") -> None:
        """
        Cancel an Outlook calendar event (sends cancellation notices to attendees).

        Args:
            event_id: Graph API event ID.
            comment:  Cancellation message shown to attendees.

        Raises:
            GraphClientError on failure.
        """
        response = requests.post(
            f"{self._events_url(event_id)}/cancel",
            json={"comment": comment},
            headers=self._headers(),
            timeout=15,
        )
        self._raise_for_status(response, f"cancel_event(event_id={event_id})")
        logger.info("Outlook event cancelled | event_id=%s", event_id)
