"""
Comprehensive database service for planning/calendar integration.
Handles all CRUD operations for sessions, calendar invites, events, and message tracking.
"""

import psycopg2
import psycopg2.extras
import logging
import json
from datetime import datetime
from typing import Optional, Dict, List
from enum import Enum
from db_config import get_db_config

logger = logging.getLogger(__name__)

# Database connection parameters
DB_CONFIG = get_db_config()


class MessageStatus(Enum):
    RECEIVED = "received"
    PROCESSED = "processed"
    FAILED = "failed"
    DUPLICATE = "duplicate"


def _get_connection():
    """Create and return a database connection."""
    try:
        conn = psycopg2.connect(
            host=DB_CONFIG["host"],
            port=int(DB_CONFIG["port"]),
            database=DB_CONFIG["name"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
        )
        return conn
    except psycopg2.Error as e:
        logger.error("Database connection failed: %s", e)
        raise


# ============================================================================
# MESSAGE LOG (Idempotency & Tracking)
# ============================================================================

class MessageLog:
    """Manages message-level idempotency and status tracking."""

    @staticmethod
    def log_message(
        message_id: str,
        message_type: str,
        source: str,
        timestamp: str,
        correlation_id: Optional[str] = None,
        status: str = MessageStatus.RECEIVED.value,
        error_message: Optional[str] = None,
    ) -> bool:
        """
        Log message for idempotency tracking.
        Returns True if logged successfully (new message), False if duplicate.
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            INSERT INTO message_log
            (message_id, message_type, source, timestamp, correlation_id, status, error_message)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(
                query,
                (message_id, message_type, source, timestamp, correlation_id, status, error_message),
            )

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Message logged | type=%s | message_id=%s | source=%s",
                message_type,
                message_id,
                source,
            )
            return True

        except psycopg2.IntegrityError:
            logger.warning("Duplicate message (already processed): %s", message_id)
            return False
        except psycopg2.Error as e:
            logger.error("Database error while logging message: %s", e)
            return False

    @staticmethod
    def update_message_status(
        message_id: str, status: str, error_message: Optional[str] = None
    ) -> bool:
        """Update message processing status."""
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            UPDATE message_log
            SET status = %s, error_message = %s, processed_at = NOW(), attempts = attempts + 1
            WHERE message_id = %s
            """

            cursor.execute(query, (status, error_message, message_id))
            conn.commit()
            cursor.close()
            conn.close()

            logger.info("Message status updated | message_id=%s | status=%s", message_id, status)
            return True

        except psycopg2.Error as e:
            logger.error("Database error while updating message status: %s", e)
            return False

    @staticmethod
    def get_message(message_id: str) -> Optional[Dict]:
        """Get message log entry."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            query = "SELECT * FROM message_log WHERE message_id = %s"
            cursor.execute(query, (message_id,))

            row = cursor.fetchone()
            cursor.close()
            conn.close()

            return dict(row) if row else None

        except psycopg2.Error as e:
            logger.error("Database error while retrieving message log: %s", e)
            return None


# ============================================================================
# SESSIONS MANAGEMENT (session_created, session_updated, session_deleted)
# ============================================================================

class SessionService:
    """Manages session lifecycle and data."""

    @staticmethod
    def create_or_update(
        session_id: str,
        title: str,
        start_datetime: str,
        end_datetime: str,
        location: str = "",
        session_type: str = "keynote",
        status: str = "published",
        max_attendees: int = 0,
        current_attendees: int = 0,
    ) -> bool:
        """
        Create or update a session (upsert).
        Returns True on success, False on failure.
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            INSERT INTO sessions
            (session_id, title, start_datetime, end_datetime, location, session_type, status, max_attendees, current_attendees)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (session_id) DO UPDATE
            SET title = EXCLUDED.title,
                start_datetime = EXCLUDED.start_datetime,
                end_datetime = EXCLUDED.end_datetime,
                location = EXCLUDED.location,
                session_type = EXCLUDED.session_type,
                status = EXCLUDED.status,
                max_attendees = EXCLUDED.max_attendees,
                current_attendees = EXCLUDED.current_attendees,
                updated_at = NOW(),
                is_deleted = FALSE,
                deleted_at = NULL
            """

            cursor.execute(
                query,
                (
                    session_id,
                    title,
                    start_datetime,
                    end_datetime,
                    location,
                    session_type,
                    status,
                    max_attendees,
                    current_attendees,
                ),
            )

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Session created/updated | session_id=%s | title=%s | status=%s",
                session_id,
                title,
                status,
            )
            return True

        except psycopg2.Error as e:
            logger.error("Database error while creating/updating session: %s", e)
            return False

    @staticmethod
    def delete(session_id: str, reason: str = "", deleted_by: str = "system") -> bool:
        """
        Soft-delete a session (mark as deleted, keep record).
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            UPDATE sessions
            SET is_deleted = TRUE, deleted_at = NOW(), status = 'deleted'
            WHERE session_id = %s
            """

            cursor.execute(query, (session_id,))
            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Session deleted | session_id=%s | reason=%s | deleted_by=%s",
                session_id,
                reason,
                deleted_by,
            )
            return True

        except psycopg2.Error as e:
            logger.error("Database error while deleting session: %s", e)
            return False

    @staticmethod
    def get(session_id: str, include_deleted: bool = False) -> Optional[Dict]:
        """Retrieve a session by session_id."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            where = "" if include_deleted else "AND is_deleted = FALSE"

            query = f"""
            SELECT session_id, title, start_datetime, end_datetime, location, 
                   session_type, status, max_attendees, current_attendees, created_at, updated_at
            FROM sessions
            WHERE session_id = %s {where}
            """

            cursor.execute(query, (session_id,))
            row = cursor.fetchone()
            cursor.close()
            conn.close()

            return dict(row) if row else None

        except psycopg2.Error as e:
            logger.error("Database error while retrieving session: %s", e)
            return None

    @staticmethod
    def list_all(limit: int = 50, include_deleted: bool = False) -> List[Dict]:
        """Retrieve sessions."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            where = "" if include_deleted else "WHERE is_deleted = FALSE"

            query = f"""
            SELECT session_id, title, start_datetime, end_datetime, location, 
                   session_type, status, max_attendees, current_attendees, created_at, updated_at
            FROM sessions
            {where}
            ORDER BY created_at DESC
            LIMIT %s
            """

            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            return [dict(row) for row in rows]

        except psycopg2.Error as e:
            logger.error("Database error while listing sessions: %s", e)
            return []


# ============================================================================
# CALENDAR INVITES (calendar.invite messages - incoming)
# ============================================================================

class CalendarInviteService:
    """Manages incoming calendar invite messages."""

    @staticmethod
    def create(
        message_id: str,
        timestamp: str,
        source: str,
        type_: str,
        session_id: str,
        title: str,
        start_datetime: str,
        end_datetime: str,
        location: str = "",
        status: str = "pending",
        user_id: Optional[str] = None,
    ) -> bool:
        """
        Insert a calendar invite into the database.
        Returns True on success, False if duplicate.
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            # Ensure session exists first
            cursor.execute(
                """INSERT INTO sessions (session_id, title, start_datetime, end_datetime, location)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (session_id) DO NOTHING""",
                (session_id, title, start_datetime, end_datetime, location),
            )

            query = """
            INSERT INTO calendar_invites
            (message_id, timestamp, source, type, session_id, title, start_datetime, end_datetime, location, status, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """

            cursor.execute(
                query,
                (
                    message_id,
                    timestamp,
                    source,
                    type_,
                    session_id,
                    title,
                    start_datetime,
                    end_datetime,
                    location,
                    status,
                    user_id,
                ),
            )

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Calendar invite created | message_id=%s | session_id=%s | title=%s",
                message_id,
                session_id,
                title,
            )
            return True

        except psycopg2.IntegrityError:
            logger.warning("Duplicate calendar invite (already processed): %s", message_id)
            return False
        except psycopg2.Error as e:
            logger.error("Database error while creating calendar invite: %s", e)
            return False

    @staticmethod
    def get(message_id: str) -> Optional[Dict]:
        """Retrieve a calendar invite by message_id."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            query = """
            SELECT message_id, timestamp, source, type, session_id, title,
                   start_datetime, end_datetime, location, status, received_at
            FROM calendar_invites WHERE message_id = %s
            """

            cursor.execute(query, (message_id,))
            row = cursor.fetchone()
            cursor.close()
            conn.close()

            return dict(row) if row else None

        except psycopg2.Error as e:
            logger.error("Database error while retrieving calendar invite: %s", e)
            return None

    @staticmethod
    def list_all(limit: int = 50, status: Optional[str] = None) -> List[Dict]:
        """Retrieve calendar invites, optionally filtered by status."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            where = f"WHERE status = %s" if status else ""

            query = f"""
            SELECT message_id, timestamp, source, type, session_id, title,
                   start_datetime, end_datetime, location, status, received_at
            FROM calendar_invites
            {where}
            ORDER BY received_at DESC
            LIMIT %s
            """

            params = ([status, limit] if status else [limit])
            cursor.execute(query, params)

            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            return [dict(row) for row in rows]

        except psycopg2.Error as e:
            logger.error("Database error while listing calendar invites: %s", e)
            return []

    @staticmethod
    def update_status(
        message_id: str, status: str, processed_at: Optional[str] = None
    ) -> bool:
        """Update the status of a calendar invite."""
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            UPDATE calendar_invites
            SET status = %s, processed_at = COALESCE(%s, NOW())
            WHERE message_id = %s
            """

            cursor.execute(query, (status, processed_at, message_id))
            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Calendar invite status updated | message_id=%s | status=%s",
                message_id,
                status,
            )
            return True

        except psycopg2.Error as e:
            logger.error("Database error while updating calendar invite status: %s", e)
            return False


# ============================================================================
# SESSION EVENTS (Audit trail for all changes)
# ============================================================================

class SessionEventService:
    """Manages session event audit trail."""

    @staticmethod
    def log_event(
        message_id: str,
        timestamp: str,
        source: str,
        event_type: str,
        session_id: str,
        version: str = "1.0",
        correlation_id: Optional[str] = None,
        event_data: Optional[Dict] = None,
    ) -> bool:
        """
        Log a session event for audit trail.
        Event types: session_created, session_updated, session_deleted, etc.
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            INSERT INTO session_events
            (message_id, timestamp, source, type, session_id, version, correlation_id, event_data)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """

            event_data_json = json.dumps(event_data) if event_data else None

            cursor.execute(
                query,
                (
                    message_id,
                    timestamp,
                    source,
                    event_type,
                    session_id,
                    version,
                    correlation_id,
                    event_data_json,
                ),
            )

            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Session event logged | type=%s | session_id=%s | message_id=%s",
                event_type,
                session_id,
                message_id,
            )
            return True

        except psycopg2.IntegrityError:
            logger.warning("Duplicate session event (already logged): %s", message_id)
            return False
        except psycopg2.Error as e:
            logger.error("Database error while logging session event: %s", e)
            return False

    @staticmethod
    def list_for_session(session_id: str, limit: int = 50) -> List[Dict]:
        """Retrieve audit trail for a session."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            query = """
            SELECT message_id, timestamp, source, type, session_id, version, 
                   correlation_id, event_data, received_at, processed_at
            FROM session_events
            WHERE session_id = %s
            ORDER BY received_at DESC
            LIMIT %s
            """

            cursor.execute(query, (session_id, limit))
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            return [dict(row) for row in rows]

        except psycopg2.Error as e:
            logger.error("Database error while retrieving session events: %s", e)
            return []


# ============================================================================
# SESSION VIEW REQUESTS (Request-response tracking)
# ============================================================================

class SessionViewRequestService:
    """Manages session view request/response pairs."""

    @staticmethod
    def log_request(
        message_id: str,
        timestamp: str,
        source: str,
        session_id: Optional[str] = None,
        version: str = "1.0",
        correlation_id: Optional[str] = None,
    ) -> bool:
        """Log incoming session_view_request."""
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            INSERT INTO session_view_requests
            (message_id, timestamp, source, session_id, version, correlation_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            """

            cursor.execute(query, (message_id, timestamp, source, session_id, version, correlation_id))
            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Session view request logged | message_id=%s | session_id=%s",
                message_id,
                session_id,
            )
            return True

        except psycopg2.IntegrityError:
            logger.warning("Duplicate session view request: %s", message_id)
            return False
        except psycopg2.Error as e:
            logger.error("Database error while logging session view request: %s", e)
            return False

    @staticmethod
    def mark_responded(
        request_id: int, status: str = "ok", response_sent_at: Optional[str] = None
    ) -> bool:
        """Mark a session_view_request as responded."""
        try:
            conn = _get_connection()
            cursor = conn.cursor()

            query = """
            UPDATE session_view_requests
            SET response_status = %s, response_sent_at = COALESCE(%s, NOW())
            WHERE request_id = %s
            """

            cursor.execute(query, (status, response_sent_at, request_id))
            conn.commit()
            cursor.close()
            conn.close()

            logger.info(
                "Session view request marked as responded | request_id=%s | status=%s",
                request_id,
                status,
            )
            return True

        except psycopg2.Error as e:
            logger.error("Database error while marking view request as responded: %s", e)
            return False

    @staticmethod
    def get_pending() -> List[Dict]:
        """Get pending view requests."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)

            query = """
            SELECT request_id, message_id, timestamp, source, session_id, 
                   version, correlation_id, response_status, received_at
            FROM session_view_requests
            WHERE response_status = 'pending'
            ORDER BY received_at ASC
            LIMIT 50
            """

            cursor.execute(query)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()

            return [dict(row) for row in rows]

        except psycopg2.Error as e:
            logger.error("Database error while retrieving pending view requests: %s", e)
            return []


# ============================================================================
# ICS FEEDS (per-user iCalendar subscription management)
# ============================================================================

class IcsFeedService:
    """
    Manages ICS feed tokens for non-Outlook users.

    One row per user in ics_feeds:
      - feed_token: secret UUID that protects the /ical/{user_id}?token=... URL
    """

    @staticmethod
    def get_or_create(user_id: str) -> Optional[Dict]:
        """Return an existing feed record or create a new one."""
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute(
                "INSERT INTO ics_feeds (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            conn.commit()
            cursor.execute(
                "SELECT user_id, feed_token::text FROM ics_feeds WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(row) if row else None
        except psycopg2.Error as e:
            logger.error("IcsFeedService.get_or_create failed | user_id=%s | error=%s", user_id, e)
            return None

    @staticmethod
    def validate_token(user_id: str, feed_token: str) -> bool:
        """Return True if feed_token matches the stored token for user_id."""
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM ics_feeds WHERE user_id = %s AND feed_token::text = %s",
                (user_id, feed_token),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return row is not None
        except psycopg2.Error as e:
            logger.error("IcsFeedService.validate_token failed | user_id=%s | error=%s", user_id, e)
            return False

    @staticmethod
    def get_user_sessions(user_id: str) -> List[Dict]:
        """
        Return all active sessions this user has been invited to, ordered by start time.
        Joins calendar_invites.user_id → sessions.
        """
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute(
                """
                SELECT DISTINCT
                    s.session_id,
                    s.title,
                    s.start_datetime,
                    s.end_datetime,
                    s.location
                FROM sessions s
                INNER JOIN calendar_invites ci ON ci.session_id = s.session_id
                WHERE ci.user_id = %s
                  AND s.is_deleted = FALSE
                ORDER BY s.start_datetime
                """,
                (user_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [dict(row) for row in rows]
        except psycopg2.Error as e:
            logger.error("IcsFeedService.get_user_sessions failed | user_id=%s | error=%s", user_id, e)
            return []
