-- Add user_id to calendar_invites for per-user ICS feed queries
ALTER TABLE calendar_invites ADD COLUMN IF NOT EXISTS user_id TEXT;
CREATE INDEX IF NOT EXISTS idx_calendar_invites_user_id ON calendar_invites(user_id);

-- ICS feeds: one record per non-Outlook user
-- feed_token is the secret that protects the public /ical/{user_id}?token=... URL
CREATE TABLE IF NOT EXISTS ics_feeds (
    user_id     TEXT        PRIMARY KEY,
    feed_token  UUID        NOT NULL DEFAULT gen_random_uuid(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION update_ics_feeds_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_ics_feeds_updated_at ON ics_feeds;
CREATE TRIGGER trg_ics_feeds_updated_at
    BEFORE UPDATE ON ics_feeds
    FOR EACH ROW EXECUTE FUNCTION update_ics_feeds_updated_at();
