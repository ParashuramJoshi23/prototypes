-- AI Interviewer results schema.
-- Applied automatically on first boot by docker-compose, and idempotently by
-- the app at startup (app/db.py), so it is safe to run repeatedly.

-- One row per interview session (room).
CREATE TABLE IF NOT EXISTS interviews (
    room          TEXT PRIMARY KEY,
    survey_id     TEXT NOT NULL,
    survey_title  TEXT NOT NULL,
    participant   TEXT NOT NULL,
    started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ
);

-- One row per recorded answer.
CREATE TABLE IF NOT EXISTS answers (
    id            BIGSERIAL PRIMARY KEY,
    room          TEXT NOT NULL REFERENCES interviews(room) ON DELETE CASCADE,
    question_id   TEXT NOT NULL,
    question_text TEXT NOT NULL,
    answer        TEXT NOT NULL,
    sentiment     TEXT,
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Verbatim turn-by-turn transcript (participant STT + agent TTS lines).
CREATE TABLE IF NOT EXISTS transcript (
    id          BIGSERIAL PRIMARY KEY,
    room        TEXT NOT NULL REFERENCES interviews(room) ON DELETE CASCADE,
    role        TEXT NOT NULL,           -- 'user' or 'assistant'
    text        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_answers_room       ON answers(room, recorded_at);
CREATE INDEX IF NOT EXISTS idx_transcript_room    ON transcript(room, created_at);
CREATE INDEX IF NOT EXISTS idx_interviews_started ON interviews(started_at DESC);
