"""
Graph service — orchestrates Microsoft Graph API calls with DB sync tracking.

Each (session_id, user_id) pair gets its own row in graph_sync because every
user's Outlook calendar holds a separate copy of the event with a unique
Graph event_id.

When a session is updated or deleted the service looks up all subscribed users
from calendar_invites, retrieves each user's token, and patches/cancels their
individual Outlook event.
"""

import logging
from typing import List, Optional

import psycopg2
from psycopg2.extras import DictCursor

from db_config import get_database_url
from graph_client import GraphClient, GraphClientError
from token_service import TokenService

logger = logging.getLogger(__name__)

_DB_URL: Optional[str] = get_database_url()


def _get_conn():
    return psycopg2.connect(_DB_URL, cursor_factory=DictCursor)


# ---------------------------------------------------------------------------
# graph_sync DB helpers  (keyed on session_id + user_id)
# ---------------------------------------------------------------------------

def _upsert_sync(session_id: str, user_id: str, event_id: str, status: str = "synced") -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO graph_sync
                    (session_id, user_id, graph_event_id, sync_status, last_synced_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (session_id, user_id) DO UPDATE SET
                    graph_event_id = EXCLUDED.graph_event_id,
                    sync_status    = EXCLUDED.sync_status,
                    last_synced_at = NOW(),
                    error_message  = NULL
                """,
                (session_id, user_id, event_id, status),
            )


def _mark_sync_failed(session_id: str, user_id: str, error: str) -> None:
    try:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO graph_sync
                        (session_id, user_id, graph_event_id, sync_status, error_message, last_synced_at)
                    VALUES (%s, %s, NULL, 'failed', %s, NOW())
                    ON CONFLICT (session_id, user_id) DO UPDATE SET
                        sync_status   = 'failed',
                        error_message = EXCLUDED.error_message,
                        last_synced_at = NOW()
                    """,
                    (session_id, user_id, error),
                )
    except Exception as exc:
        logger.warning(
            "Could not persist sync failure | session_id=%s | user_id=%s | error=%s",
            session_id, user_id, exc,
        )


def _get_event_id(session_id: str, user_id: str) -> Optional[str]:
    """Return the Graph event_id for a specific (session, user) pair."""
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT graph_event_id FROM graph_sync "
                "WHERE session_id = %s AND user_id = %s AND sync_status = 'synced'",
                (session_id, user_id),
            )
            row = cur.fetchone()
            return row["graph_event_id"] if row else None


def _mark_sync_deleted(session_id: str, user_id: str) -> None:
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE graph_sync SET sync_status = 'deleted', last_synced_at = NOW() "
                "WHERE session_id = %s AND user_id = %s",
                (session_id, user_id),
            )


def _get_outlook_users_for_session(session_id: str) -> List[str]:
    """
    Return the user_ids of all users who registered for this session
    AND have a valid Outlook token stored.
    """
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ci.user_id
                FROM calendar_invites ci
                INNER JOIN user_tokens ut ON ut.user_id = ci.user_id
                WHERE ci.session_id = %s AND ci.user_id IS NOT NULL
                """,
                (session_id,),
            )
            return [row["user_id"] for row in cur.fetchall()]


# ---------------------------------------------------------------------------
# Client builder
# ---------------------------------------------------------------------------

def _build_client(user_id: str) -> Optional[GraphClient]:
    """
    Build a GraphClient using the stored per-user token.
    Returns None (and logs a warning) when no valid token is available.
    """
    try:
        access_token = TokenService.get_valid_token(user_id)
    except Exception as exc:
        logger.warning(
            "Could not retrieve token for user_id=%s — Outlook sync disabled: %s",
            user_id, exc,
        )
        return None

    if not access_token:
        logger.warning(
            "No token registered for user_id=%s — Outlook sync disabled", user_id
        )
        return None

    return GraphClient(access_token=access_token)


# ---------------------------------------------------------------------------
# GraphService — public API used by consumer.py
# ---------------------------------------------------------------------------

class GraphService:
    """
    Static-method facade for Graph API + sync DB operations.

    For every Outlook user registered to a session, their event is created,
    updated, or cancelled individually using their personal token.
    Non-Outlook users are served by the ICS feed and are not touched here.
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
        Create an Outlook event for user_id and store the (session_id, user_id)
        mapping.  Returns True on success, False on failure.
        """
        if not user_id:
            return False

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
            _upsert_sync(session_id, user_id, event_id, status="synced")
            logger.info(
                "Graph sync created | session_id=%s | user_id=%s | event_id=%s",
                session_id, user_id, event_id,
            )
            return True

        except GraphClientError as exc:
            logger.error(
                "Graph create_event failed | session_id=%s | user_id=%s | error=%s",
                session_id, user_id, exc,
            )
            _mark_sync_failed(session_id, user_id, str(exc))
            return False

        except Exception as exc:
            logger.error(
                "Unexpected error during Graph sync create | session_id=%s | user_id=%s | error=%s",
                session_id, user_id, exc, exc_info=True,
            )
            _mark_sync_failed(session_id, user_id, str(exc))
            return False

    @staticmethod
    def sync_updated(
        session_id: str,
        title: str,
        start_datetime: str,
        end_datetime: str,
        location: str = "",
    ) -> bool:
        """
        Update the Outlook event for every user subscribed to this session.

        Looks up all users with Outlook tokens registered for session_id from
        calendar_invites, then patches each user's individual event.
        Returns True if all updates succeeded, False if any failed.
        """
        user_ids = _get_outlook_users_for_session(session_id)
        if not user_ids:
            logger.info(
                "No Outlook users found for session_id=%s — skipping Graph update",
                session_id,
            )
            return True

        all_ok = True
        for user_id in user_ids:
            client = _build_client(user_id)
            if client is None:
                all_ok = False
                continue

            try:
                event_id = _get_event_id(session_id, user_id)
                if event_id:
                    client.update_event(
                        event_id=event_id,
                        title=title,
                        start_datetime=start_datetime,
                        end_datetime=end_datetime,
                        location=location,
                    )
                    _upsert_sync(session_id, user_id, event_id, status="synced")
                    logger.info(
                        "Graph sync updated | session_id=%s | user_id=%s | event_id=%s",
                        session_id, user_id, event_id,
                    )
                else:
                    # No prior sync record — create the event instead
                    logger.warning(
                        "No synced event found for session_id=%s user_id=%s — creating instead",
                        session_id, user_id,
                    )
                    GraphService.sync_created(
                        session_id=session_id,
                        title=title,
                        start_datetime=start_datetime,
                        end_datetime=end_datetime,
                        location=location,
                        user_id=user_id,
                    )

            except GraphClientError as exc:
                logger.error(
                    "Graph update_event failed | session_id=%s | user_id=%s | error=%s",
                    session_id, user_id, exc,
                )
                _mark_sync_failed(session_id, user_id, str(exc))
                all_ok = False

            except Exception as exc:
                logger.error(
                    "Unexpected error during Graph sync update | session_id=%s | user_id=%s | error=%s",
                    session_id, user_id, exc, exc_info=True,
                )
                _mark_sync_failed(session_id, user_id, str(exc))
                all_ok = False

        return all_ok

    @staticmethod
    def sync_deleted(
        session_id: str,
        reason: str = "Session cancelled",
    ) -> bool:
        """
        Cancel the Outlook event for every user subscribed to this session.
        Returns True if all cancellations succeeded (or nothing to cancel).
        """
        user_ids = _get_outlook_users_for_session(session_id)
        if not user_ids:
            logger.info(
                "No Outlook users found for session_id=%s — skipping Graph cancel",
                session_id,
            )
            return True

        all_ok = True
        for user_id in user_ids:
            client = _build_client(user_id)
            if client is None:
                all_ok = False
                continue

            try:
                event_id = _get_event_id(session_id, user_id)
                if not event_id:
                    logger.info(
                        "No synced event to cancel | session_id=%s | user_id=%s — skipping",
                        session_id, user_id,
                    )
                    continue

                client.cancel_event(event_id=event_id, comment=reason)
                _mark_sync_deleted(session_id, user_id)
                logger.info(
                    "Graph sync deleted | session_id=%s | user_id=%s | event_id=%s",
                    session_id, user_id, event_id,
                )

            except GraphClientError as exc:
                logger.error(
                    "Graph cancel_event failed | session_id=%s | user_id=%s | error=%s",
                    session_id, user_id, exc,
                )
                _mark_sync_failed(session_id, user_id, str(exc))
                all_ok = False

            except Exception as exc:
                logger.error(
                    "Unexpected error during Graph sync delete | session_id=%s | user_id=%s | error=%s",
                    session_id, user_id, exc, exc_info=True,
                )
                _mark_sync_failed(session_id, user_id, str(exc))
                all_ok = False

        return all_ok
