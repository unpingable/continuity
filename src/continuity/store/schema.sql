-- continuity schema v0.1
--
-- Three-layer design:
--   1. memory_objects  — materialized current state
--   2. memory_events   — append-only mutation log
--   3. receipts        — hash-chained attestations
-- Plus:
--   memory_links       — provenance/dependency graph
--   spool_imports      — async ingest tracking

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA temp_store = MEMORY;

BEGIN;

-- Layer 1: materialized memory state
CREATE TABLE IF NOT EXISTS memory_objects (
    memory_id       TEXT PRIMARY KEY,
    scope           TEXT NOT NULL,
    kind            TEXT NOT NULL CHECK (
        kind IN (
            'fact',
            'note',
            'decision',
            'hypothesis',
            'summary',
            'constraint',
            'project_state',
            'next_action'
        )
    ),
    basis           TEXT NOT NULL CHECK (
        basis IN (
            'direct_capture',
            'operator_assertion',
            'inference',
            'import',
            'synthesis'
        )
    ),
    status          TEXT NOT NULL CHECK (
        status IN (
            'observed',
            'committed',
            'revoked'
        )
    ),
    reliance_class  TEXT NOT NULL CHECK (
        reliance_class IN (
            'none',
            'retrieve_only',
            'advisory',
            'actionable'
        )
    ),
    confidence      REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),

    content_json      TEXT NOT NULL CHECK (json_valid(content_json)),
    source_refs_json  TEXT NOT NULL CHECK (json_valid(source_refs_json)),

    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    expires_at  TEXT NULL,

    supersedes    TEXT NULL REFERENCES memory_objects(memory_id),
    revoked_by    TEXT NULL REFERENCES memory_objects(memory_id),

    created_by_json   TEXT NULL CHECK (created_by_json IS NULL OR json_valid(created_by_json)),
    approved_by_json  TEXT NULL CHECK (approved_by_json IS NULL OR json_valid(approved_by_json))
);

-- Layer 3: hash-chained receipts (created before events that reference them)
CREATE TABLE IF NOT EXISTS receipts (
    receipt_id    TEXT PRIMARY KEY,
    receipt_type  TEXT NOT NULL CHECK (
        receipt_type IN (
            'memory.observe',
            'memory.commit',
            'memory.revoke',
            'memory.repair',
            'memory.import'
        )
    ),
    hash          TEXT NOT NULL UNIQUE,
    prev_hash     TEXT NULL,
    content_json  TEXT NOT NULL CHECK (json_valid(content_json)),
    created_at    TEXT NOT NULL
);

-- Layer 2: append-only mutation log
CREATE TABLE IF NOT EXISTS memory_events (
    event_id    TEXT PRIMARY KEY,
    memory_id   TEXT NOT NULL REFERENCES memory_objects(memory_id) ON DELETE RESTRICT,
    event_type  TEXT NOT NULL CHECK (
        event_type IN (
            'observe',
            'commit',
            'revoke',
            'repair',
            'import'
        )
    ),

    actor_json    TEXT NULL CHECK (actor_json IS NULL OR json_valid(actor_json)),
    standing_json TEXT NULL CHECK (standing_json IS NULL OR json_valid(standing_json)),

    receipt_id      TEXT NOT NULL REFERENCES receipts(receipt_id) ON DELETE RESTRICT,
    payload_json    TEXT NOT NULL CHECK (json_valid(payload_json)),

    created_at      TEXT NOT NULL,
    idempotency_key TEXT NULL
);

-- Async ingest tracking
CREATE TABLE IF NOT EXISTS spool_imports (
    import_id     TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    external_ref  TEXT NULL,
    status        TEXT NOT NULL CHECK (
        status IN (
            'pending',
            'applied',
            'rejected'
        )
    ),
    reason      TEXT NULL,
    created_at  TEXT NOT NULL,
    applied_at  TEXT NULL
);

-- Provenance/dependency graph
CREATE TABLE IF NOT EXISTS memory_links (
    link_id         TEXT PRIMARY KEY,

    dst_memory_id   TEXT NOT NULL
        REFERENCES memory_objects(memory_id) ON DELETE RESTRICT,

    src_memory_id   TEXT NULL
        REFERENCES memory_objects(memory_id) ON DELETE RESTRICT,

    src_receipt_id  TEXT NULL
        REFERENCES receipts(receipt_id) ON DELETE RESTRICT,

    src_ref_json    TEXT NULL
        CHECK (src_ref_json IS NULL OR json_valid(src_ref_json)),

    relation  TEXT NOT NULL CHECK (
        relation IN (
            'depends_on',
            'supports',
            'derived_from',
            'implements',
            'supersedes',
            'invalidates',
            'about'
        )
    ),

    strength  TEXT NOT NULL CHECK (
        strength IN ('hard', 'soft')
    ),

    status  TEXT NOT NULL CHECK (
        status IN ('active', 'revoked')
    ),

    note  TEXT NULL,

    created_at          TEXT NOT NULL,
    created_by_event_id TEXT NULL
        REFERENCES memory_events(event_id) ON DELETE RESTRICT,

    revoked_at          TEXT NULL,
    revoked_by_event_id TEXT NULL
        REFERENCES memory_events(event_id) ON DELETE RESTRICT,

    -- Exactly one source must be set
    CHECK (
        (CASE WHEN src_memory_id IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN src_receipt_id IS NOT NULL THEN 1 ELSE 0 END) +
        (CASE WHEN src_ref_json  IS NOT NULL THEN 1 ELSE 0 END) = 1
    )
);

-- Indexes: memory_objects
CREATE INDEX IF NOT EXISTS idx_memory_objects_scope
    ON memory_objects(scope);

CREATE INDEX IF NOT EXISTS idx_memory_objects_kind
    ON memory_objects(kind);

CREATE INDEX IF NOT EXISTS idx_memory_objects_status
    ON memory_objects(status);

CREATE INDEX IF NOT EXISTS idx_memory_objects_scope_kind_status
    ON memory_objects(scope, kind, status);

CREATE INDEX IF NOT EXISTS idx_memory_objects_reliance_class
    ON memory_objects(reliance_class);

CREATE INDEX IF NOT EXISTS idx_memory_objects_expires_at
    ON memory_objects(expires_at);

-- Indexes: memory_events
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_events_idempotency
    ON memory_events(idempotency_key)
    WHERE idempotency_key IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_memory_events_memory_id_created_at
    ON memory_events(memory_id, created_at);

CREATE INDEX IF NOT EXISTS idx_memory_events_receipt_id
    ON memory_events(receipt_id);

-- Indexes: receipts
CREATE INDEX IF NOT EXISTS idx_receipts_created_at
    ON receipts(created_at);

-- Indexes: spool_imports
CREATE INDEX IF NOT EXISTS idx_spool_imports_status_created_at
    ON spool_imports(status, created_at);

-- Indexes: memory_links
CREATE INDEX IF NOT EXISTS idx_memory_links_dst
    ON memory_links(dst_memory_id, status, relation);

CREATE INDEX IF NOT EXISTS idx_memory_links_src_memory
    ON memory_links(src_memory_id, status, relation);

CREATE INDEX IF NOT EXISTS idx_memory_links_src_receipt
    ON memory_links(src_receipt_id, status, relation);

CREATE INDEX IF NOT EXISTS idx_memory_links_created_by_event
    ON memory_links(created_by_event_id);

-- Idempotent link insertion: same semantic edge = same link
CREATE UNIQUE INDEX IF NOT EXISTS idx_memory_links_unique_active
    ON memory_links (
        dst_memory_id,
        COALESCE(src_memory_id, ''),
        COALESCE(src_receipt_id, ''),
        COALESCE(src_ref_json, ''),
        relation,
        strength,
        status
    );

-- Auto-update updated_at on memory_objects mutation
CREATE TRIGGER IF NOT EXISTS trg_memory_objects_updated_at
AFTER UPDATE ON memory_objects
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE memory_objects
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE memory_id = NEW.memory_id;
END;

COMMIT;
