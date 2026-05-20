"""
Per-user OAuth token service — PostgreSQL via psycopg2.
Stores encrypted Microsoft access + refresh tokens in user_tokens table.
"""

import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Optional

import msal
import psycopg2
from cryptography.fernet import Fernet, InvalidToken
from psycopg2.extras import DictCursor

from db_config import get_database_url

logger = logging.getLogger(__name__)

_AUTHORITY = "https://login.microsoftonline.com/common"
_SCOPES = ["User.Read", "Calendars.ReadWrite"]

_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
_DB_URL: Optional[str] = get_database_url()


def _get_fernet() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not set.")
    return Fernet(key.encode())


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Token decryption failed") from exc


def _get_conn():
    return psycopg2.connect(_DB_URL, cursor_factory=DictCursor)


class TokenService:

    @staticmethod
    def store(user_id: str, access_token: str, refresh_token: str, expires_at: datetime) -> None:
        enc_access = _encrypt(access_token)
        enc_refresh = _encrypt(refresh_token)
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO user_tokens
                        (user_id, access_token_enc, refresh_token_enc, expires_at)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (user_id) DO UPDATE SET
                        access_token_enc  = EXCLUDED.access_token_enc,
                        refresh_token_enc = EXCLUDED.refresh_token_enc,
                        expires_at        = EXCLUDED.expires_at
                    """,
                    (user_id, enc_access, enc_refresh, expires_at),
                )
        logger.info("Stored tokens for user_id=%s", user_id)

    @staticmethod
    def get_valid_token(user_id: str) -> Optional[str]:
        row = TokenService._load_row(user_id)
        if row is None:
            return None

        access_token = _decrypt(row["access_token_enc"])
        expires_at: datetime = row["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at - datetime.now(tz=timezone.utc) > timedelta(minutes=5):
            return access_token

        return TokenService._refresh(user_id, _decrypt(row["refresh_token_enc"]))

    @staticmethod
    def _load_row(user_id: str) -> Optional[dict]:
        with _get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT access_token_enc, refresh_token_enc, expires_at "
                    "FROM user_tokens WHERE user_id = %s",
                    (user_id,),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    @staticmethod
    def _refresh(user_id: str, refresh_token: str) -> str:
        if not all([_CLIENT_ID, _CLIENT_SECRET]):
            raise RuntimeError("AZURE_CLIENT_ID / AZURE_CLIENT_SECRET not set")

        msal_app = msal.ConfidentialClientApplication(
            _CLIENT_ID, authority=_AUTHORITY, client_credential=_CLIENT_SECRET,
        )
        result = msal_app.acquire_token_by_refresh_token(refresh_token, scopes=_SCOPES)

        if "access_token" not in result:
            raise RuntimeError(f"Token refresh failed: {result.get('error')}")

        new_expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=int(result.get("expires_in", 3600)))
        TokenService.store(user_id, result["access_token"], result.get("refresh_token", refresh_token), new_expires_at)
        return result["access_token"]
