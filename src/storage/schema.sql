PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS auction_session (
    session_id TEXT PRIMARY KEY,
    session_type TEXT NOT NULL,
    title TEXT NOT NULL,
    scheduled_end_time TEXT,
    source_url TEXT NOT NULL,
    discovered_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lot (
    lot_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    title_raw TEXT NOT NULL,
    description_raw TEXT,
    category TEXT,
    grade_agency TEXT,
    grade_score TEXT,
    end_time TEXT,
    status TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES auction_session(session_id)
);

CREATE INDEX IF NOT EXISTS idx_lot_session_id ON lot(session_id);
CREATE INDEX IF NOT EXISTS idx_lot_end_time ON lot(end_time);

CREATE TABLE IF NOT EXISTS lot_detail (
    lot_id TEXT PRIMARY KEY,
    title_raw TEXT NOT NULL,
    description_raw TEXT,
    current_price NUMERIC,
    start_price NUMERIC,
    end_time TEXT,
    status TEXT NOT NULL,
    bid_count INTEGER,
    look_count INTEGER,
    fee_rate NUMERIC,
    winner TEXT,
    bid_history_html TEXT,
    image_primary TEXT,
    images_json TEXT,
    video_url TEXT,
    labels_json TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(lot_id) REFERENCES lot(lot_id)
);

CREATE TABLE IF NOT EXISTS lot_classification (
    lot_id TEXT PRIMARY KEY,
    category_l1 TEXT NOT NULL,
    category_l2 TEXT,
    tags_json TEXT,
    rule_hit TEXT NOT NULL,
    confidence_score NUMERIC NOT NULL,
    classifier_version TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(lot_id) REFERENCES lot(lot_id)
);

CREATE INDEX IF NOT EXISTS idx_lot_classification_l1 ON lot_classification(category_l1);

CREATE TABLE IF NOT EXISTS lot_structured (
    lot_id TEXT PRIMARY KEY,
    coin_type TEXT,
    variety TEXT,
    mint_year TEXT,
    grading_company TEXT,
    grade_score TEXT,
    denomination TEXT,
    special_tags_json TEXT,
    confidence_score NUMERIC NOT NULL,
    extract_source TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    raw_structured_json TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(lot_id) REFERENCES lot(lot_id)
);

CREATE INDEX IF NOT EXISTS idx_lot_structured_coin_type ON lot_structured(coin_type);
CREATE INDEX IF NOT EXISTS idx_lot_structured_confidence ON lot_structured(confidence_score);

CREATE TABLE IF NOT EXISTS review_queue (
    review_id TEXT PRIMARY KEY,
    queue_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    confidence_score NUMERIC NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(queue_type, entity_type, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_review_queue_status ON review_queue(status);
CREATE INDEX IF NOT EXISTS idx_review_queue_entity ON review_queue(entity_type, entity_id);

CREATE TABLE IF NOT EXISTS lot_snapshot (
    snapshot_id TEXT PRIMARY KEY,
    lot_id TEXT NOT NULL,
    snapshot_time TEXT NOT NULL,
    snapshot_type TEXT NOT NULL,
    current_price NUMERIC,
    bid_count INTEGER,
    raw_ref TEXT NOT NULL,
    quality_score NUMERIC NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    FOREIGN KEY(lot_id) REFERENCES lot(lot_id)
);

CREATE INDEX IF NOT EXISTS idx_snapshot_lot_id ON lot_snapshot(lot_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_time ON lot_snapshot(snapshot_time);

CREATE TABLE IF NOT EXISTS lot_result (
    lot_id TEXT PRIMARY KEY,
    final_price NUMERIC,
    final_end_time TEXT,
    is_withdrawn INTEGER NOT NULL DEFAULT 0,
    is_unsold INTEGER NOT NULL DEFAULT 0,
    confidence_score NUMERIC NOT NULL,
    decided_from_snapshot TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(lot_id) REFERENCES lot(lot_id)
);

CREATE TABLE IF NOT EXISTS task_state (
    task_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    run_at TEXT NOT NULL,
    priority INTEGER NOT NULL,
    status TEXT NOT NULL,
    retry_count INTEGER NOT NULL,
    max_retries INTEGER NOT NULL,
    last_error TEXT,
    dedupe_key TEXT NOT NULL UNIQUE,
    payload_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_task_run_at ON task_state(run_at);
CREATE INDEX IF NOT EXISTS idx_task_status ON task_state(status);
CREATE INDEX IF NOT EXISTS idx_task_event_entity ON task_state(event_type, entity_id);
