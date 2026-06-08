-- Hashtag Service — PostgreSQL schema
-- SQLAlchemy creates this automatically on startup via Base.metadata.create_all().
-- This file is reference documentation; run it manually to inspect or pre-create.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ── users ─────────────────────────────────────────────────────────────────────
CREATE TABLE users (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    username   VARCHAR(50)  UNIQUE NOT NULL,
    email      VARCHAR(255) UNIQUE NOT NULL,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

-- ── posts ─────────────────────────────────────────────────────────────────────
-- status lifecycle: draft → active  (media posts pass through draft)
--                   draft → failed  (on processing error)
--   Text-only posts skip draft and are written as 'active' directly.
CREATE TABLE posts (
    id           UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      UUID         NOT NULL REFERENCES users(id),
    caption      TEXT         NOT NULL,
    media_s3_key VARCHAR(500),           -- NULL for text-only posts
    status       VARCHAR(20)  NOT NULL DEFAULT 'draft',
    created_at   TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_posts_user_id    ON posts(user_id);
CREATE INDEX idx_posts_status     ON posts(status);
CREATE INDEX idx_posts_created_at ON posts(created_at DESC);

-- ── hashtags ──────────────────────────────────────────────────────────────────
-- tag is stored lowercase without a leading '#'.
-- post_count is the denormalised total; incremented atomically via UPDATE.
CREATE TABLE hashtags (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    tag        VARCHAR(100) UNIQUE NOT NULL,
    post_count BIGINT       NOT NULL DEFAULT 0,
    created_at TIMESTAMP    NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_hashtags_tag        ON hashtags(tag);
CREATE INDEX idx_hashtags_post_count ON hashtags(post_count DESC);

-- ── post_hashtags ─────────────────────────────────────────────────────────────
-- Many-to-many join. Populated by the Kafka consumer after post.created fires.
CREATE TABLE post_hashtags (
    post_id    UUID      NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    hashtag_id UUID      NOT NULL REFERENCES hashtags(id) ON DELETE CASCADE,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (post_id, hashtag_id)
);

CREATE INDEX idx_post_hashtags_hashtag_id ON post_hashtags(hashtag_id);

-- ── notifications ─────────────────────────────────────────────────────────────
-- In-app notifications. Written by the Kafka consumer on notification.inapp events.
--
-- type values (extensible):
--   hashtag_created     – user coined a new hashtag
--   hashtag_incremented – (reserved for future use, not currently sent to users)
--   post_tagged         – (reserved for future tagging/mention features)
CREATE TABLE notifications (
    id         UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID         NOT NULL REFERENCES users(id),
    type       VARCHAR(50)  NOT NULL,
    title      VARCHAR(255) NOT NULL,
    body       TEXT,
    is_read    BOOLEAN      NOT NULL DEFAULT FALSE,
    payload    JSONB,                   -- flexible context: tag, post_id, etc.
    created_at TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_notifications_user_id    ON notifications(user_id);
CREATE INDEX idx_notifications_unread     ON notifications(user_id, is_read) WHERE is_read = FALSE;
CREATE INDEX idx_notifications_created_at ON notifications(created_at DESC);
