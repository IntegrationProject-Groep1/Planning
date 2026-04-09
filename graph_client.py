"""
Microsoft Graph API client for Outlook calendar management.

Authentication uses the OAuth2 client credentials flow (app-only).
Requires an Azure app registration with the Calendars.ReadWrite
application permission granted and admin-consented.

Required environment variables:
    AZURE_TENANT_ID      – Azure AD tenant ID
    AZURE_CLIENT_ID      – App registration client ID
    AZURE_CLIENT_SECRET  – App registration client secret
    GRAPH_CALENDAR_USER  – UPN or object ID of the mailbox to manage
                           (e.g. planning@yourdomain.onmicrosoft.com)
"""

import logging
import os
from typing import Optional

import msal
import requests

logger = logging.getLogger(__name__)

GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
_SCOPE = ["https://graph.microsoft.com/.default"]

# Read once at import time; values can still be overridden via env before
# GraphClient() is constructed.
_TENANT_ID = os.getenv("AZURE_TENANT_ID", "")
_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
_CALENDAR_USER = os.getenv("GRAPH_CALENDAR_USER", "")


class GraphClientError(Exception):
    """Raised when a Graph API call fails after all retries."""


class GraphClient:
    """
    Thin wrapper around Microsoft Graph API for Outlook calendar events.

    One instance is safe to reuse across calls — MSAL caches the token
    internally and refreshes it transparently when it expires.
    """

    def __init__(
        self,
        tenant_id: str = "",
        client_id: str = "",
        client_secret: str = "",
        calendar_user: str = "",
    ):
        self._tenant_id = tenant_id or _TENANT_ID
        self._client_id = client_id or _CLIENT_ID
        self._client_secret = client_secret or _CLIENT_SECRET
        self._calendar_user = calendar_user or _CALENDAR_USER

        if not all([self._tenant_id, self._client_id, self._client_secret]):
            raise GraphClientError(
                "Graph API credentials not configured. "
                "Set AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET."
            )

        self._msal_app = msal.ConfidentialClientApplication(
            self._client_id,
            authority=f"https://login.microsoftonline.com/{self._tenant_id}",
            client_credential=self._client_secret,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """Acquire an access token, using the MSAL cache when possible."""
        result = self._msal_app.acquire_token_silent(_SCOPE, account=None)
        if not result:
            result = self._msal_app.acquire_token_for_client(scopes=_SCOPE)
        if "access_token" not in result:
            raise GraphClientError(
                f"Failed to acquire Graph API token: "
                f"{result.get('error')} – {result.get('error_description')}"
            )
        return result["access_token"]

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    def _user_events_url(self, event_id: Optional[str] = None) -> str:
        base = f"{GRAPH_BASE_URL}/users/{self._calendar_user}/calendar/events"
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
        if not self._calendar_user:
            raise GraphClientError(
                "GRAPH_CALENDAR_USER is not set — cannot create calendar event."
            )

        payload = {
            "subject": title,
            "start": {"dateTime": start_datetime, "timeZone": "UTC"},
            "end": {"dateTime": end_datetime, "timeZone": "UTC"},
            "transactionId": session_id,  # idempotency key
        }
        if location:
            payload["location"] = {"displayName": location}

        response = requests.post(
            self._user_events_url(),
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
        if not self._calendar_user:
            raise GraphClientError(
                "GRAPH_CALENDAR_USER is not set — cannot update calendar event."
            )

        payload: dict = {
            "subject": title,
            "start": {"dateTime": start_datetime, "timeZone": "UTC"},
            "end": {"dateTime": end_datetime, "timeZone": "UTC"},
        }
        if location:
            payload["location"] = {"displayName": location}

        response = requests.patch(
            self._user_events_url(event_id),
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
        if not self._calendar_user:
            raise GraphClientError(
                "GRAPH_CALENDAR_USER is not set — cannot cancel calendar event."
            )

        response = requests.post(
            f"{self._user_events_url(event_id)}/cancel",
            json={"comment": comment},
            headers=self._headers(),
            timeout=15,
        )
        self._raise_for_status(response, f"cancel_event(event_id={event_id})")
        logger.info("Outlook event cancelled | event_id=%s", event_id)
