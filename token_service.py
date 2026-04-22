"""
Per-user OAuth token service.

Responsibilities:
  - Encrypt and store a user's access + refresh tokens in the user_tokens table.
  - Retrieve a valid access token for a user, refreshing via MSAL when expired.
  - Tokens are encrypted at rest using Fernet (symmetric encryption).

Required environment variable:
    TOKEN_ENCRYPTION_KEY  – URL-safe base64-encoded 32-byte Fernet key.
                            Generate one with:
                              python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

This module is the only layer that reads/writes the user_tokens table.
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


# ---------------------------------------------------------------------------
# Encryption helpers
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY is not set. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def _encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def _decrypt(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Token decryption failed — encryption key may have changed") from exc


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _get_conn():
    return psycopg2.connect(_DB_URL, cursor_factory=DictCursor)


# ---------------------------------------------------------------------------
# TokenService — public API
# ---------------------------------------------------------------------------

class TokenService:
    """
    Manages per-user OAuth tokens in the encrypted user_tokens table.

    Usage:
        # Called by POST /api/tokens when Drupal registers a user's tokens:
        TokenService.store(user_id, access_token, refresh_token, expires_at)

        # Called by GraphService before each Graph API call:
        access_token = TokenService.get_valid_token(user_id)
    """

    @staticmethod
    def store(
        user_id: str,
        access_token: str,
        refresh_token: str,
        expires_at: datetime,
    ) -> None:
        """
        Encrypt and persist (or update) a user's OAuth tokens.

        Args:
            user_id:       Identifier from Drupal (e.g. "usr_123").
            access_token:  Raw Microsoft access token.
            refresh_token: Raw Microsoft refresh token.
            expires_at:    When the access token expires (UTC-aware datetime).
        """
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
        logger.info("Stored tokens for user_id=%s | expires_at=%s", user_id, expires_at)

    @staticmethod
    def get_valid_token(user_id: str) -> Optional[str]:
        """
        Return a valid access token for the user, refreshing via MSAL if expired.

        Returns None if no tokens are registered for the user.
        Raises RuntimeError if the refresh fails.
        """
        row = TokenService._load_row(user_id)
        if row is None:
            logger.warning("No tokens registered for user_id=%s", user_id)
            return None

        access_token = _decrypt(row["access_token_enc"])
        expires_at: datetime = row["expires_at"]

        # Refresh if the token expires within the next 5 minutes
        now = datetime.now(tz=timezone.utc)
        if expires_at - now > timedelta(minutes=5):
            return access_token

        logger.info("Access token expired for user_id=%s — refreshing", user_id)
        refresh_token = _decrypt(row["refresh_token_enc"])
        return TokenService._refresh(user_id, refresh_token)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
        """Use MSAL to exchange a refresh token for a new access + refresh token pair."""
        if not all([_CLIENT_ID, _CLIENT_SECRET]):
            raise RuntimeError(
                "AZURE_CLIENT_ID / AZURE_CLIENT_SECRET not set — cannot refresh token"
            )

        msal_app = msal.ConfidentialClientApplication(
            _CLIENT_ID,
            authority=_AUTHORITY,
            client_credential=_CLIENT_SECRET,
        )

        result = msal_app.acquire_token_by_refresh_token(refresh_token, scopes=_SCOPES)

        if "access_token" not in result:
            error = result.get("error", "unknown")
            desc = result.get("error_description", "")
            raise RuntimeError(
                f"Token refresh failed for user_id={user_id}: {error} — {desc}"
            )

        new_access = result["access_token"]
        new_refresh = result.get("refresh_token", refresh_token)  # MSAL may omit if unchanged
        expires_in = result.get("expires_in", 3600)
        new_expires_at = datetime.now(tz=timezone.utc) + timedelta(seconds=int(expires_in))

        TokenService.store(user_id, new_access, new_refresh, new_expires_at)
        logger.info("Token refreshed for user_id=%s | new_expires_at=%s", user_id, new_expires_at)
        return new_access
