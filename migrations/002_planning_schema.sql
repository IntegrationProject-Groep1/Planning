-- Migration 002: Planning integration schema
-- Comprehensive schema for all planning service message types

-- Sessions table (from session_created, session_updated, session_deleted)
CREATE TABLE IF NOT EXISTS sessions (
    session_id          TEXT        PRIMARY KEY,
    title               TEXT        NOT NULL,
    start_datetime      TIMESTAMPTZ NOT NULL,
    end_datetime        TIMESTAMPTZ NOT NULL,
    location            TEXT        DEFAULT '',
    session_type        TEXT        DEFAULT 'keynote',
    status              TEXT        DEFAULT 'published',
    max_attendees       INTEGER     DEFAULT 0,
    current_attendees   INTEGER     DEFAULT 0,
    
    -- Tracking
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ,
    is_deleted          BOOLEAN     DEFAULT FALSE
);

-- Calendar invites (from calendar.invite messages - incoming)
CREATE TABLE IF NOT EXISTS calendar_invites (
    -- Header fields
    message_id          TEXT        PRIMARY KEY,
    timestamp           TIMESTAMPTZ NOT NULL,
    source              TEXT        NOT NULL,
    type                TEXT        NOT NULL,
    
    -- Body fields
    session_id          TEXT        NOT NULL REFERENCES sessions(session_id),
    title               TEXT        NOT NULL,
    start_datetime      TIMESTAMPTZ NOT NULL,
    end_datetime        TIMESTAMPTZ NOT NULL,
    location            TEXT        DEFAULT '',
    
    -- Status tracking
    status              TEXT        DEFAULT 'pending',
    processed_at        TIMESTAMPTZ,
    
    -- Audit
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Session events log (audit trail for all session changes)
CREATE TABLE IF NOT EXISTS session_events (
    id                  SERIAL      PRIMARY KEY,
    message_id          TEXT        NOT NULL UNIQUE,
    timestamp           TIMESTAMPTZ NOT NULL,
    source              TEXT        NOT NULL,
    type                TEXT        NOT NULL,
    session_id          TEXT        NOT NULL REFERENCES sessions(session_id),
    version             TEXT        DEFAULT '1.0',
    correlation_id      TEXT,
    
    -- Event details (JSON for flexibility)
    event_data          JSONB,
    
    -- Tracking
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at        TIMESTAMPTZ
);

-- View requests tracking
CREATE TABLE IF NOT EXISTS session_view_requests (
    request_id          SERIAL      PRIMARY KEY,
    message_id          TEXT        NOT NULL UNIQUE,
    timestamp           TIMESTAMPTZ NOT NULL,
    source              TEXT        NOT NULL,
    session_id          TEXT,
    version             TEXT        DEFAULT '1.0',
    correlation_id      TEXT,
    
    -- Response details
    response_status     TEXT        DEFAULT 'pending',
    response_sent_at    TIMESTAMPTZ,
    
    -- Tracking
    received_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Message processing log (for idempotency)
CREATE TABLE IF NOT EXISTS message_log (
    message_id          TEXT        PRIMARY KEY,
    message_type        TEXT        NOT NULL,
    source              TEXT        NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    correlation_id      TEXT,
    
    -- Status
    status              TEXT        DEFAULT 'received',
    error_message       TEXT,
    
    -- Tracking
    processed_at        TIMESTAMPTZ DEFAULT NOW(),
    attempts            INTEGER     DEFAULT 1
);

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_deleted ON sessions(is_deleted);
CREATE INDEX IF NOT EXISTS idx_sessions_datetime ON sessions(start_datetime, end_datetime);
CREATE INDEX IF NOT EXISTS idx_calendar_invites_session ON calendar_invites(session_id);
CREATE INDEX IF NOT EXISTS idx_calendar_invites_status ON calendar_invites(status);
CREATE INDEX IF NOT EXISTS idx_session_events_session ON session_events(session_id);
CREATE INDEX IF NOT EXISTS idx_session_events_type ON session_events(type);
CREATE INDEX IF NOT EXISTS idx_message_log_type ON message_log(message_type);
CREATE INDEX IF NOT EXISTS idx_message_log_status ON message_log(status);
