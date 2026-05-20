"""
Database service for planning/calendar integration — PostgreSQL via psycopg2.
"""

import psycopg2
import psycopg2.extras
import logging
from typing import Optional, Dict, List
from enum import Enum
from db_config import get_db_config

logger = logging.getLogger(__name__)

DB_CONFIG = get_db_config()


class MessageStatus(Enum):
    RECEIVED = "received"
    PROCESSED = "processed"
    FAILED = "failed"
    DUPLICATE = "duplicate"


def _get_connection():
    try:
        return psycopg2.connect(
            host=DB_CONFIG["host"],
            port=int(DB_CONFIG["port"]),
            database=DB_CONFIG["name"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
        )
    except psycopg2.Error as e:
        logger.error("Database connection failed: %s", e)
        raise


class UserService:
    @staticmethod
    def save(master_uuid: str, email: str) -> bool:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO users (master_uuid, email)
                VALUES (%s, %s)
                ON CONFLICT (master_uuid) DO UPDATE SET email = EXCLUDED.email
                """,
                (master_uuid, email),
            )
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except psycopg2.Error as e:
            logger.error("UserService.save failed: %s", e)
            return False

    @staticmethod
    def get_by_email(email: str) -> Optional[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute(
                "SELECT master_uuid, user_id::text, email FROM users WHERE email = %s",
                (email,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(row) if row else None
        except psycopg2.Error as e:
            logger.error("UserService.get_by_email failed: %s", e)
            return None

    @staticmethod
    def get_by_master_uuid(master_uuid: str) -> Optional[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute(
                "SELECT master_uuid, user_id::text, email FROM users WHERE master_uuid = %s",
                (master_uuid,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(row) if row else None
        except psycopg2.Error as e:
            logger.error("UserService.get_by_master_uuid failed: %s", e)
            return None


class SessionService:
    @staticmethod
    def create_or_update(**kwargs) -> bool:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessions
                    (session_id, title, start_datetime, end_datetime, location,
                     session_type, status, max_attendees, price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id) DO UPDATE SET
                    title          = EXCLUDED.title,
                    start_datetime = EXCLUDED.start_datetime,
                    end_datetime   = EXCLUDED.end_datetime,
                    location       = EXCLUDED.location,
                    session_type   = EXCLUDED.session_type,
                    status         = EXCLUDED.status,
                    max_attendees  = EXCLUDED.max_attendees,
                    price          = EXCLUDED.price
                """,
                (
                    kwargs.get("session_id"), kwargs.get("title"),
                    kwargs.get("start_datetime"), kwargs.get("end_datetime"),
                    kwargs.get("location", ""), kwargs.get("session_type", "keynote"),
                    kwargs.get("status", "published"), kwargs.get("max_attendees", 0),
                    kwargs.get("price"),
                ),
            )
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except psycopg2.Error as e:
            logger.error("SessionService.create_or_update failed: %s", e)
            return False

    @staticmethod
    def delete(session_id: str) -> bool:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET is_deleted = TRUE, deleted_at = NOW() WHERE session_id = %s",
                (session_id,),
            )
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except psycopg2.Error as e:
            logger.error("SessionService.delete failed: %s", e)
            return False

    @staticmethod
    def increment_attendees(session_id: str):
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET current_attendees = current_attendees + 1 "
                "WHERE session_id = %s RETURNING current_attendees, max_attendees",
                (session_id,),
            )
            row = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            return (row[0], row[1]) if row else (-1, 0)
        except psycopg2.Error as e:
            logger.error("SessionService.increment_attendees failed: %s", e)
            return (-1, 0)

    @staticmethod
    def get(session_id: str) -> Optional[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM sessions WHERE session_id = %s AND is_deleted = FALSE",
                (session_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return row
        except psycopg2.Error as e:
            logger.error("SessionService.get failed: %s", e)
            return None

    @staticmethod
    def list_all(limit: Optional[int] = None) -> List[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            query = "SELECT * FROM sessions WHERE is_deleted = FALSE ORDER BY start_datetime"
            params: tuple = ()
            if limit is not None:
                query += " LIMIT %s"
                params = (limit,)
            cursor.execute(query, params)
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return rows
        except psycopg2.Error as e:
            logger.error("SessionService.list_all failed: %s", e)
            return []

    @staticmethod
    def decrement_attendees(session_id: str):
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE sessions SET current_attendees = GREATEST(current_attendees - 1, 0) "
                "WHERE session_id = %s RETURNING current_attendees, max_attendees",
                (session_id,),
            )
            row = cursor.fetchone()
            conn.commit()
            cursor.close()
            conn.close()
            return (row[0], row[1]) if row else (-1, 0)
        except psycopg2.Error as e:
            logger.error("SessionService.decrement_attendees failed: %s", e)
            return (-1, 0)


class SessionRegistrationService:
    @staticmethod
    def register(session_id: str, master_uuid: str) -> bool:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE master_uuid = %s", (master_uuid,))
            row = cursor.fetchone()
            if row is None:
                cursor.close()
                conn.close()
                return False
            user_id = row[0]
            cursor.execute(
                """
                INSERT INTO session_registrations (session_id, user_id, status)
                VALUES (%s, %s, 'confirmed')
                ON CONFLICT (session_id, user_id) DO UPDATE SET status = 'confirmed'
                """,
                (session_id, user_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except psycopg2.Error as e:
            logger.error("SessionRegistrationService.register failed: %s", e)
            return False

    @staticmethod
    def cancel(session_id: str, master_uuid: str) -> bool:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM users WHERE master_uuid = %s", (master_uuid,))
            row = cursor.fetchone()
            if row is None:
                cursor.close()
                conn.close()
                return False
            user_id = row[0]
            cursor.execute(
                "UPDATE session_registrations SET status = 'cancelled' "
                "WHERE session_id = %s AND user_id = %s",
                (session_id, user_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except psycopg2.Error as e:
            logger.error("SessionRegistrationService.cancel failed: %s", e)
            return False


    @staticmethod
    def list_for_session(session_id: str) -> List[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute(
                """
                SELECT sr.session_id, u.user_id::text, u.master_uuid, u.email, sr.status
                FROM session_registrations sr
                INNER JOIN users u ON u.user_id = sr.user_id
                WHERE sr.session_id = %s
                """,
                (session_id,),
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [dict(row) for row in rows]
        except psycopg2.Error as e:
            logger.error("SessionRegistrationService.list_for_session failed: %s", e)
            return []


class IcsFeedService:
    @staticmethod
    def get_or_create(master_uuid: str) -> Optional[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute("SELECT user_id FROM users WHERE master_uuid = %s", (master_uuid,))
            row = cursor.fetchone()
            if row is None:
                cursor.close()
                conn.close()
                return None
            user_id = row[0]
            cursor.execute(
                "INSERT INTO ics_feeds (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (user_id,),
            )
            conn.commit()
            cursor.execute(
                "SELECT user_id::text, feed_token::text FROM ics_feeds WHERE user_id = %s",
                (user_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return dict(row) if row else None
        except psycopg2.Error as e:
            logger.error("IcsFeedService.get_or_create failed: %s", e)
            return None

    @staticmethod
    def get_master_uuid_by_token(feed_token: str) -> Optional[str]:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT u.master_uuid FROM ics_feeds f
                INNER JOIN users u ON u.user_id = f.user_id
                WHERE f.feed_token::text = %s
                """,
                (feed_token,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return row[0] if row else None
        except psycopg2.Error as e:
            logger.error("IcsFeedService.get_master_uuid_by_token failed: %s", e)
            return None

    @staticmethod
    def get_user_sessions(master_uuid: str) -> List[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
            cursor.execute(
                """
                SELECT s.session_id, s.title, s.start_datetime, s.end_datetime,
                       s.location, s.session_type, s.status,
                       s.max_attendees, s.current_attendees, s.price
                FROM sessions s
                INNER JOIN session_registrations sr ON sr.session_id = s.session_id
                INNER JOIN users u ON u.user_id = sr.user_id
                WHERE u.master_uuid = %s
                  AND sr.status = 'confirmed'
                  AND s.is_deleted = FALSE
                ORDER BY s.start_datetime
                """,
                (master_uuid,),
            )
            rows = cursor.fetchall()
            cursor.close()
            conn.close()
            return [dict(row) for row in rows]
        except psycopg2.Error as e:
            logger.error("IcsFeedService.get_user_sessions failed: %s", e)
            return []


class MessageLog:
    @staticmethod
    def log_message(message_id: str, message_type: str, source: str = "",
                    timestamp: str = "", correlation_id: str = "") -> bool:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO message_log (message_id, message_type, source, timestamp, correlation_id, status)
                VALUES (%s, %s, %s, %s, %s, 'received')
                ON CONFLICT (message_id) DO NOTHING
                """,
                (message_id, message_type, source, timestamp, correlation_id),
            )
            inserted = cursor.rowcount > 0
            conn.commit()
            cursor.close()
            conn.close()
            return inserted
        except psycopg2.Error as e:
            logger.error("MessageLog.log_message failed: %s", e)
            return False

    @staticmethod
    def update_message_status(message_id: str, status: str) -> bool:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE message_log SET status = %s, processed_at = NOW() WHERE message_id = %s",
                (status, message_id),
            )
            conn.commit()
            cursor.close()
            conn.close()
            return True
        except psycopg2.Error as e:
            logger.error("MessageLog.update_message_status failed: %s", e)
            return False

    @staticmethod
    def get_message(message_id: str) -> Optional[Dict]:
        try:
            conn = _get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM message_log WHERE message_id = %s",
                (message_id,),
            )
            row = cursor.fetchone()
            cursor.close()
            conn.close()
            return row
        except psycopg2.Error as e:
            logger.error("MessageLog.get_message failed: %s", e)
            return None
