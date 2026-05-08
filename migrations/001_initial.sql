-- Migration 001: Initial schema
-- Stores incoming calendar.invite messages

CREATE TABLE IF NOT EXISTS calendar_invites (
    -- Header fields
    message_id      TEXT        PRIMARY KEY,
    timestamp       TIMESTAMPTZ NOT NULL,
    source          TEXT        NOT NULL,
    type            TEXT        NOT NULL,

    -- Body fields
    session_id      TEXT        NOT NULL,
    title           TEXT        NOT NULL,
    start_datetime  TIMESTAMPTZ NOT NULL,
    end_datetime    TIMESTAMPTZ NOT NULL,
    location        TEXT        NOT NULL DEFAULT '',

    -- Audit
    received_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
