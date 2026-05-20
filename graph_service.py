"""
Graph service — Microsoft Graph API sync with PostgreSQL tracking.
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
                        sync_status    = 'failed',
                        error_message  = EXCLUDED.error_message,
                        last_synced_at = NOW()
                    """,
                    (session_id, user_id, error),
                )
    except Exception as exc:
        logger.warning("Could not persist sync failure: %s", exc)


def _get_event_id(session_id: str, user_id: str) -> Optional[str]:
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
    with _get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT u.master_uuid
                FROM session_registrations sr
                INNER JOIN users u ON u.user_id = sr.user_id
                INNER JOIN user_tokens ut ON ut.user_id = u.master_uuid
                WHERE sr.session_id = %s AND sr.status = 'confirmed'
                """,
                (session_id,),
            )
            return [row["master_uuid"] for row in cur.fetchall()]


def _build_client(user_id: str) -> Optional[GraphClient]:
    try:
        access_token = TokenService.get_valid_token(user_id)
    except Exception as exc:
        logger.warning("Could not retrieve token for user_id=%s: %s", user_id, exc)
        return None
    if not access_token:
        return None
    return GraphClient(access_token=access_token)


class GraphService:

    @staticmethod
    def sync_created(session_id: str, title: str, start_datetime: str,
                     end_datetime: str, location: str = "", user_id: Optional[str] = None) -> bool:
        if not user_id:
            return False
        client = _build_client(user_id)
        if client is None:
            return False
        try:
            event_id = client.create_event(
                session_id=session_id, title=title,
                start_datetime=start_datetime, end_datetime=end_datetime, location=location,
            )
            _upsert_sync(session_id, user_id, event_id, status="synced")
            logger.info("Graph sync created | session_id=%s | user_id=%s", session_id, user_id)
            return True
        except GraphClientError as exc:
            _mark_sync_failed(session_id, user_id, str(exc))
            return False
        except Exception as exc:
            _mark_sync_failed(session_id, user_id, str(exc))
            return False

    @staticmethod
    def sync_updated(session_id: str, title: str, start_datetime: str,
                     end_datetime: str, location: str = "") -> bool:
        user_ids = _get_outlook_users_for_session(session_id)
        if not user_ids:
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
                    GraphService.sync_created(session_id, title, start_datetime, end_datetime, location, user_id)
                    continue
                client.update_event(event_id=event_id, title=title,
                                    start_datetime=start_datetime, end_datetime=end_datetime, location=location)
                _upsert_sync(session_id, user_id, event_id, status="synced")
            except Exception as exc:
                _mark_sync_failed(session_id, user_id, str(exc))
                all_ok = False
        return all_ok

    @staticmethod
    def sync_deleted(session_id: str, reason: str = "Session cancelled") -> bool:
        user_ids = _get_outlook_users_for_session(session_id)
        if not user_ids:
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
                    continue
                client.cancel_event(event_id=event_id, comment=reason)
                _mark_sync_deleted(session_id, user_id)
            except Exception as exc:
                _mark_sync_failed(session_id, user_id, str(exc))
                all_ok = False
        return all_ok

    @staticmethod
    def sync_deleted_for_user(session_id: str, master_uuid: str,
                              reason: str = "Unsubscribed by attendee") -> bool:
        client = _build_client(master_uuid)
        if client is None:
            return True
        try:
            event_id = _get_event_id(session_id, master_uuid)
            if not event_id:
                return True
            client.cancel_event(event_id=event_id, comment=reason)
            _mark_sync_deleted(session_id, master_uuid)
            return True
        except Exception as exc:
            _mark_sync_failed(session_id, master_uuid, str(exc))
            return False
