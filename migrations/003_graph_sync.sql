-- Migration 003: graph_sync table
-- Tracks the mapping between a planning session and its Outlook calendar event.
-- Used by graph_service.py to create, update, and cancel events via Graph API.

CREATE TABLE IF NOT EXISTS graph_sync (
    session_id      VARCHAR(255) PRIMARY KEY,
    graph_event_id  VARCHAR(512),               -- Outlook event ID returned by Graph API
    sync_status     VARCHAR(50)  NOT NULL DEFAULT 'pending',
                                                -- pending | synced | failed | deleted
    last_synced_at  TIMESTAMP WITH TIME ZONE,
    error_message   TEXT,                       -- populated when sync_status = 'failed'
    created_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
);

-- Index for quick lookups by sync status (e.g. find all failed syncs)
CREATE INDEX IF NOT EXISTS idx_graph_sync_status ON graph_sync (sync_status);

-- Auto-update updated_at on every row change
CREATE OR REPLACE FUNCTION set_graph_sync_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_graph_sync_updated_at ON graph_sync;
CREATE TRIGGER trg_graph_sync_updated_at
    BEFORE UPDATE ON graph_sync
    FOR EACH ROW EXECUTE FUNCTION set_graph_sync_updated_at();
