-- Migration 009: FK constraints — all user-referencing tables point to users.user_id
-- session_registrations and ics_feeds use the internal UUID (users.user_id)
-- user_tokens and graph_sync keep TEXT user_id (master_uuid) for token service compatibility

-- 1. session_registrations: convert user_id TEXT → UUID, add FK → users.user_id
ALTER TABLE session_registrations ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
ALTER TABLE session_registrations
    ADD CONSTRAINT fk_session_reg_user
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;

-- 2. user_tokens: add FK → users.master_uuid (token service uses master_uuid as key)
ALTER TABLE user_tokens
    ADD CONSTRAINT fk_user_tokens_user
    FOREIGN KEY (user_id) REFERENCES users(master_uuid) ON DELETE CASCADE;

-- 3. graph_sync: add FK → users.master_uuid (graph service uses master_uuid as key)
ALTER TABLE graph_sync
    ADD CONSTRAINT fk_graph_sync_user
    FOREIGN KEY (user_id) REFERENCES users(master_uuid) ON DELETE CASCADE;

-- 4. ics_feeds: convert user_id TEXT → UUID, add FK → users.user_id
ALTER TABLE ics_feeds ALTER COLUMN user_id TYPE UUID USING user_id::uuid;
ALTER TABLE ics_feeds
    ADD CONSTRAINT fk_ics_feeds_user
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE;
