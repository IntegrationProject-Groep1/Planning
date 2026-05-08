-- Replace the single session_id PK with a composite (session_id, user_id) key
-- so each user's individual Outlook event_id is tracked separately.

-- Drop the old trigger and table, recreate with the new schema.
DROP TRIGGER IF EXISTS trg_graph_sync_updated_at ON graph_sync;
DROP TABLE IF EXISTS graph_sync;

CREATE TABLE graph_sync (
    session_id      TEXT        NOT NULL,
    user_id         TEXT        NOT NULL,
    graph_event_id  TEXT,
    sync_status     TEXT        NOT NULL DEFAULT 'pending'
                                CHECK (sync_status IN ('pending','synced','failed','deleted')),
    error_message   TEXT,
    last_synced_at  TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (session_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_sync_session ON graph_sync(session_id);
CREATE INDEX IF NOT EXISTS idx_graph_sync_user    ON graph_sync(user_id);

CREATE OR REPLACE FUNCTION update_graph_sync_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_graph_sync_updated_at
    BEFORE UPDATE ON graph_sync
    FOR EACH ROW EXECUTE FUNCTION update_graph_sync_updated_at();
