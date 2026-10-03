-- Idempotent: safe to run on every startup.
-- gen_random_uuid() is built in on Postgres 13+.

CREATE TABLE IF NOT EXISTS uploads (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename         TEXT        NOT NULL,              -- original name, display only
    content_type     TEXT        NOT NULL,
    size_bytes       BIGINT      NOT NULL CHECK (size_bytes > 0),
    storage_key      TEXT        NOT NULL UNIQUE,       -- path inside the bucket
    language_code    TEXT        NOT NULL,              -- e.g. en-IN, hi-IN

    -- Lifecycle the frontend renders:
    -- uploading -> queued -> processing -> transcribing -> summarizing -> done | failed
    status           TEXT        NOT NULL DEFAULT 'uploading'
                     CHECK (status IN ('uploading','queued','processing',
                                       'transcribing','summarizing','done','failed')),

    duration_seconds DOUBLE PRECISION,                  -- filled by ffprobe in the worker
    chunks_total     INT         NOT NULL DEFAULT 0,
    chunks_done      INT         NOT NULL DEFAULT 0,    -- drives the progress bar

    transcript       TEXT,
    summary          TEXT,
    error_message    TEXT,                              -- human-readable, shown in the UI

    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_uploads_created_at ON uploads (created_at DESC);

-- One row per ~30s slice. Storing each chunk's result means a crashed
-- worker can resume instead of re-paying for ASR on finished chunks.
CREATE TABLE IF NOT EXISTS upload_chunks (
    upload_id   UUID        NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    idx         INT         NOT NULL,
    start_sec   DOUBLE PRECISION NOT NULL,
    status      TEXT        NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','done','failed')),
    transcript  TEXT,
    attempts    INT         NOT NULL DEFAULT 0,
    last_error  TEXT,
    PRIMARY KEY (upload_id, idx)
);

-- The background job queue, backed by Postgres.
-- A worker claims a row with SELECT ... FOR UPDATE SKIP LOCKED.
CREATE TABLE IF NOT EXISTS jobs (
    id            BIGSERIAL PRIMARY KEY,
    upload_id     UUID        NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    status        TEXT        NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','running','done','failed')),
    attempts      INT         NOT NULL DEFAULT 0,
    max_attempts  INT         NOT NULL DEFAULT 3,
    run_after     TIMESTAMPTZ NOT NULL DEFAULT now(), -- for retry backoff
    locked_at     TIMESTAMPTZ,                        -- detect dead workers
    last_error    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_claim ON jobs (run_after) WHERE status = 'queued';
-- Only one active job per upload (prevents double-enqueue on a retried /complete).
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_one_active
    ON jobs (upload_id) WHERE status IN ('queued','running');
