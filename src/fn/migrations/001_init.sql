CREATE TABLE searches (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    depth TEXT NOT NULL,
    chips_json TEXT,
    chips_origin TEXT,
    status TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    finished_at TEXT,
    rerun_of TEXT REFERENCES searches (id),
    code_sha TEXT,
    dirty INTEGER NOT NULL,
    llm_mode TEXT NOT NULL,
    settings_json TEXT NOT NULL,
    boot_id TEXT NOT NULL,
    user_id TEXT,
    contracts_version TEXT NOT NULL
);
CREATE INDEX searches_status ON searches (status);

CREATE TABLE step_runs (
    id TEXT PRIMARY KEY,
    search_id TEXT NOT NULL REFERENCES searches (id),
    seq INTEGER NOT NULL,
    step TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    input_model TEXT NOT NULL,
    output_model TEXT,
    contracts_version TEXT NOT NULL,
    cost_usd REAL NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    model TEXT,
    prompt_sha TEXT,
    error_type TEXT,
    error_message TEXT,
    traceback TEXT,
    log TEXT NOT NULL DEFAULT '',
    UNIQUE (search_id, seq)
);

CREATE TABLE step_payloads (
    step_run_id TEXT PRIMARY KEY REFERENCES step_runs (id),
    input_json TEXT NOT NULL,
    output_json TEXT
);

CREATE TABLE step_calls (
    step_run_id TEXT NOT NULL REFERENCES step_runs (id),
    seq INTEGER NOT NULL,
    kind TEXT NOT NULL,
    request TEXT NOT NULL,
    status INTEGER,
    duration_ms INTEGER NOT NULL,
    response_sha TEXT,
    response_path TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    error TEXT,
    PRIMARY KEY (step_run_id, seq)
);

CREATE TABLE persons (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    name_key TEXT NOT NULL,
    list_status TEXT NOT NULL,
    merged_into TEXT REFERENCES persons (id)
);
CREATE INDEX persons_name_key ON persons (name_key);

CREATE TABLE person_identifiers (
    scheme TEXT NOT NULL,
    value TEXT NOT NULL,
    person_id TEXT NOT NULL REFERENCES persons (id),
    UNIQUE (scheme, value)
);
CREATE INDEX person_identifiers_person ON person_identifiers (person_id);

CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    text TEXT NOT NULL,
    raw_json TEXT,
    content_hash TEXT NOT NULL,
    normalize_version INTEGER NOT NULL,
    source_date TEXT,
    date_method TEXT,
    fetched_at TEXT,
    UNIQUE (kind, url, content_hash)
);

CREATE TABLE claims (
    rowid INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    person_id TEXT NOT NULL REFERENCES persons (id),
    kind TEXT NOT NULL,
    relation TEXT,
    org_id TEXT,
    value TEXT NOT NULL,
    quote TEXT NOT NULL,
    quote_start INTEGER NOT NULL,
    quote_end INTEGER NOT NULL,
    source_id TEXT NOT NULL REFERENCES sources (id),
    claim_date TEXT,
    date_precision TEXT,
    date_method TEXT,
    valid_from TEXT,
    valid_to TEXT,
    lat REAL,
    lon REAL,
    UNIQUE (person_id, kind, value, source_id, quote_start)
);
CREATE INDEX claims_person ON claims (person_id);

CREATE VIRTUAL TABLE claims_fts USING fts5 (
    value, quote,
    content = 'claims', content_rowid = 'rowid',
    tokenize = 'porter unicode61 remove_diacritics 2'
);
CREATE TRIGGER claims_ai AFTER INSERT ON claims BEGIN
    INSERT INTO claims_fts (rowid, value, quote) VALUES (new.rowid, new.value, new.quote);
END;
CREATE TRIGGER claims_ad AFTER DELETE ON claims BEGIN
    INSERT INTO claims_fts (claims_fts, rowid, value, quote) VALUES ('delete', old.rowid, old.value, old.quote);
END;
CREATE TRIGGER claims_au AFTER UPDATE ON claims BEGIN
    INSERT INTO claims_fts (claims_fts, rowid, value, quote) VALUES ('delete', old.rowid, old.value, old.quote);
    INSERT INTO claims_fts (rowid, value, quote) VALUES (new.rowid, new.value, new.quote);
END;

CREATE TABLE candidates (
    search_id TEXT NOT NULL REFERENCES searches (id),
    person_id TEXT NOT NULL REFERENCES persons (id),
    person_ids_json TEXT NOT NULL,
    section TEXT NOT NULL,
    rank INTEGER NOT NULL,
    score REAL NOT NULL,
    lane_ranks_json TEXT NOT NULL,
    reason_claim_ids_json TEXT NOT NULL,
    tie_json TEXT NOT NULL,
    PRIMARY KEY (search_id, person_id)
);

CREATE TABLE match_flags (
    search_id TEXT NOT NULL REFERENCES searches (id),
    person_id TEXT NOT NULL REFERENCES persons (id),
    other_person_id TEXT NOT NULL REFERENCES persons (id),
    reason TEXT NOT NULL,
    shared_fact TEXT,
    PRIMARY KEY (search_id, person_id, other_person_id)
);

CREATE TABLE request_errors (
    id TEXT PRIMARY KEY,
    route TEXT NOT NULL,
    traceback TEXT NOT NULL,
    at TEXT NOT NULL
);
