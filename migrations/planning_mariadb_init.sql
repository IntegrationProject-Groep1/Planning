-- All planning tables in the planning database.
-- Executed by init_db.py at container start (idempotent via IF NOT EXISTS).

CREATE TABLE IF NOT EXISTS planning_sessions (
    session_id        VARCHAR(255) NOT NULL,
    title             TEXT         NOT NULL,
    start_datetime    VARCHAR(32)  NOT NULL,
    end_datetime      VARCHAR(32)  NOT NULL,
    location          TEXT,
    session_type      VARCHAR(50)  DEFAULT 'keynote',
    status            VARCHAR(50)  DEFAULT 'published',
    max_attendees     INT          DEFAULT 0,
    current_attendees INT          DEFAULT 0,
    price             DECIMAL(10,2),
    is_deleted        TINYINT(1)   DEFAULT 0,
    PRIMARY KEY (session_id),
    INDEX idx_status (status),
    INDEX idx_deleted (is_deleted),
    INDEX idx_start (start_datetime)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS planning_registrations (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    session_id    VARCHAR(255) NOT NULL,
    master_uuid   VARCHAR(36)  NOT NULL,
    status        VARCHAR(50)  DEFAULT 'confirmed',
    registered_at VARCHAR(32),
    ics_url       TEXT,
    UNIQUE KEY unique_registration (session_id, master_uuid),
    INDEX idx_session (session_id),
    INDEX idx_user (master_uuid)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS planning_user_tokens (
    user_id      VARCHAR(255) PRIMARY KEY COMMENT 'master_uuid from Identity Service',
    access_token_enc  LONGTEXT NOT NULL,
    refresh_token_enc LONGTEXT NOT NULL,
    expires_at   DATETIME NOT NULL,
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS planning_graph_sync (
    session_id     VARCHAR(255) NOT NULL,
    user_id        VARCHAR(255) NOT NULL COMMENT 'master_uuid',
    graph_event_id VARCHAR(512),
    sync_status    VARCHAR(50)  DEFAULT 'pending',
    error_message  LONGTEXT,
    last_synced_at DATETIME NULL,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (session_id, user_id),
    INDEX idx_gs_session (session_id),
    INDEX idx_gs_user    (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS planning_ics_feeds (
    master_uuid VARCHAR(36) PRIMARY KEY,
    feed_token  CHAR(36)    NOT NULL UNIQUE,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at  DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
