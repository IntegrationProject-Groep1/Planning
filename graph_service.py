"""
Graph service — orchestrates Microsoft Graph API calls with DB sync tracking.

Responsibilities:
  - Call graph_client.GraphClient for Outlook calendar operations.
  - Persist the session_id ↔ Graph event_id mapping in the graph_sync table.
  - Mark syncs as failed with an error message when Graph API calls fail.
  - Degrade gracefully when Graph API credentials are not configured
    (logs a warning instead of crashing the consumer).

This module is the only layer that should interact with both graph_client
and the graph_sync table.  consumer.py calls this service — it never calls
graph_client directly.
"""

import logging
import os
from typing import Optional

import psycopg2
from psycopg2.extras import DictCursor

from graph_client import GraphClient, GraphClientError
from token_service import TokenService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database helpers (reuses the same DB env vars as calendar_service.py)
# ---------------------------------------------------------------------------

_DB_URL: Optional[str] = os.getenv("DATABASE_URL") or (
    "postgresql://{user}:{password}@{host}:{port}/{db}".format(
        user=os.getenv("POSTGRES_USER", "planning_user"),
        password=os.getenv("POSTGRES_PASSWORD", ""),
        host=os.getenv("POSTGRES_HOST", "db"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        db=os.getenv("POSTGRES_DB", "planning_db"),
    )
)


def _get_conn():
    return psycopg2.connect(_DB_URL, cursor_factory=DictCursor)


# ---------------------------------------------------------------------------
# graph_sync DB helpers
# ---------------------------------------------------------------------------

def _upsert_sync(session_id: str, event_id: str, status: str = "synced") -> None:
    """Insert or update a graph_sync record for the given session."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO graph_sync
                    (session_id, graph_event_id, sync_status, last_synced_at)
                VALUES (%s, %s, %s, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    graph_event_id = EXCLUDED.graph_event_id,
                    sync_status    = EXCLUDED.sync_status,
                    last_synced_at = NOW(),
                    error_message  = NULL
                """,
                (session_id, event_id, status),
            )


def _mark_sync_failed(session_id: str, error: str) -> None:
    """Record a sync failure so it can be retried later."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO graph_sync
                    (session_id, graph_event_id, sync_status, error_message, last_synced_at)
                VALUES (%s, NULL, 'failed', %s, NOW())
                ON CONFLICT (session_id) DO UPDATE SET
                    sync_status   = 'failed',
                    error_message = EXCLUDED.error_message,
                    last_synced_at = NOW()
                """,
                (session_id, error),
            )


def _get_event_id(session_id: str) -> Optional[str]:
    """Return the Graph event ID for a synced session, or None if not found."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT graph_event_id FROM graph_sync "
                "WHERE session_id = %s AND sync_status = 'synced'",
                (session_id,),
            )
            row = cur.fetchone()
            return row["graph_event_id"] if row else None


def _mark_sync_deleted(session_id: str) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE graph_sync SET sync_status = 'deleted', last_synced_at = NOW() "
                "WHERE session_id = %s",
                (session_id,),
            )


# ---------------------------------------------------------------------------
# GraphService — public API used by consumer.py
# ---------------------------------------------------------------------------

def _build_client(user_id: Optional[str] = None) -> Optional[GraphClient]:
    """
    Try to build a GraphClient.

    When *user_id* is given, the per-user token is looked up via TokenService
    and injected directly — no MSAL file cache is involved.

    Without a user_id the shared service-account cache (auth_setup.py) is used.

    Returns None (and logs a warning) when no valid token can be obtained,
    so the consumer can continue without crashing.
    """
    if user_id:
        try:
            access_token = TokenService.get_valid_token(user_id)
        except Exception as exc:
            logger.warning(
                "Could not retrieve token for user_id=%s — Outlook sync disabled: %s",
                user_id,
                exc,
            )
            return None

        if not access_token:
            logger.warning(
                "No token registered for user_id=%s — Outlook sync disabled",
                user_id,
            )
            return None

        return GraphClient(access_token=access_token)

    try:
        return GraphClient()
    except GraphClientError as exc:
        logger.warning(
            "Graph API not configured — Outlook sync disabled: %s", exc
        )
        return None


class GraphService:
    """
    Static-method facade for Graph API + sync DB operations.
    Each method is safe to call even when Graph API is not configured.
    """

    @staticmethod
    def sync_created(
        session_id: str,
        title: str,
        start_datetime: str,
        end_datetime: str,
        location: str = "",
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Create an Outlook event for a new session and persist the mapping.

        When *user_id* is provided the calendar event is created in that user's
        Outlook calendar using their stored token.  Without it the shared
        service-account token cache is used.

        Returns True on success, False on failure (failure is logged + stored).
        """
        client = _build_client(user_id)
        if client is None:
            return False

        try:
            event_id = client.create_event(
                session_id=session_id,
                title=title,
                start_datetime=start_datetime,
                end_datetime=end_datetime,
                location=location,
            )
            _upsert_sync(session_id, event_id, status="synced")
            logger.info(
                "Graph sync created | session_id=%s | event_id=%s",
                session_id,
                event_id,
            )
            return True

        except GraphClientError as exc:
            logger.error(
                "Graph API create_event failed | session_id=%s | error=%s",
                session_id,
                exc,
            )
            _mark_sync_failed(session_id, str(exc))
            return False

        except Exception as exc:
            logger.error(
                "Unexpected error during Graph sync create | session_id=%s | error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            _mark_sync_failed(session_id, str(exc))
            return False

    @staticmethod
    def sync_updated(
        session_id: str,
        title: str,
        start_datetime: str,
        end_datetime: str,
        location: str = "",
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Update the Outlook event linked to an existing session.

        If no synced event is found in the DB, a new event is created instead.
        Returns True on success, False on failure.
        """
        client = _build_client(user_id)
        if client is None:
            return False

        try:
            event_id = _get_event_id(session_id)
            if event_id:
                client.update_event(
                    event_id=event_id,
                    title=title,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    location=location,
                )
                _upsert_sync(session_id, event_id, status="synced")
                logger.info(
                    "Graph sync updated | session_id=%s | event_id=%s",
                    session_id,
                    event_id,
                )
            else:
                # No prior sync record — create the event instead
                logger.warning(
                    "No synced event found for session_id=%s — creating instead of updating",
                    session_id,
                )
                return GraphService.sync_created(
                    session_id=session_id,
                    title=title,
                    start_datetime=start_datetime,
                    end_datetime=end_datetime,
                    location=location,
                    user_id=user_id,
                )
            return True

        except GraphClientError as exc:
            logger.error(
                "Graph API update_event failed | session_id=%s | error=%s",
                session_id,
                exc,
            )
            _mark_sync_failed(session_id, str(exc))
            return False

        except Exception as exc:
            logger.error(
                "Unexpected error during Graph sync update | session_id=%s | error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            _mark_sync_failed(session_id, str(exc))
            return False

    @staticmethod
    def sync_deleted(
        session_id: str,
        reason: str = "Session cancelled",
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Cancel the Outlook event linked to a deleted session.

        If no synced event is found, the operation is a no-op (returns True).
        Returns True on success or if there was nothing to cancel.
        Returns False on Graph API failure.
        """
        client = _build_client(user_id)
        if client is None:
            return False

        try:
            event_id = _get_event_id(session_id)
            if not event_id:
                logger.info(
                    "No synced event to cancel for session_id=%s — skipping",
                    session_id,
                )
                return True

            client.cancel_event(event_id=event_id, comment=reason)
            _mark_sync_deleted(session_id)
            logger.info(
                "Graph sync deleted | session_id=%s | event_id=%s",
                session_id,
                event_id,
            )
            return True

        except GraphClientError as exc:
            logger.error(
                "Graph API cancel_event failed | session_id=%s | error=%s",
                session_id,
                exc,
            )
            _mark_sync_failed(session_id, str(exc))
            return False

        except Exception as exc:
            logger.error(
                "Unexpected error during Graph sync delete | session_id=%s | error=%s",
                session_id,
                exc,
                exc_info=True,
            )
            _mark_sync_failed(session_id, str(exc))
            return False
