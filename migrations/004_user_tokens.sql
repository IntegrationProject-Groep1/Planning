-- Migration 004: user_tokens table
-- Stores per-user encrypted OAuth tokens registered via POST /api/tokens.
-- The planning service looks up a user's token here before calling Graph API.

CREATE TABLE IF NOT EXISTS user_tokens (
    user_id               VARCHAR(255) PRIMARY KEY,
    access_token_enc      TEXT         NOT NULL,   -- Fernet-encrypted access token
    refresh_token_enc     TEXT         NOT NULL,   -- Fernet-encrypted refresh token
    expires_at            TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Auto-update updated_at on every row change
CREATE OR REPLACE FUNCTION set_user_tokens_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_user_tokens_updated_at ON user_tokens;
CREATE TRIGGER trg_user_tokens_updated_at
    BEFORE UPDATE ON user_tokens
    FOR EACH ROW EXECUTE FUNCTION set_user_tokens_updated_at();
