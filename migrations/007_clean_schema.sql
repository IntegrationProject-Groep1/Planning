-- Migration 007: Clean schema
-- Replaces calendar_invites with session_registrations (clear user <-> session mapping)
-- Drops session_events and session_view_requests (unused in practice)

-- 1. Clean table: who is registered to which session
CREATE TABLE IF NOT EXISTS session_registrations (
    id            SERIAL      PRIMARY KEY,
    session_id    TEXT        NOT NULL REFERENCES sessions(session_id),
    user_id       TEXT        NOT NULL,
    registered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status        TEXT        NOT NULL DEFAULT 'confirmed',
    UNIQUE (session_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_session_reg_session ON session_registrations(session_id);
CREATE INDEX IF NOT EXISTS idx_session_reg_user    ON session_registrations(user_id);

-- 2. Migrate existing data from calendar_invites into session_registrations
INSERT INTO session_registrations (session_id, user_id, registered_at)
SELECT DISTINCT ci.session_id, ci.user_id, ci.received_at
FROM calendar_invites ci
WHERE ci.user_id IS NOT NULL
ON CONFLICT DO NOTHING;

-- 3. Drop obsolete tables
DROP TABLE IF EXISTS session_events;
DROP TABLE IF EXISTS session_view_requests;
DROP TABLE IF EXISTS calendar_invites;
