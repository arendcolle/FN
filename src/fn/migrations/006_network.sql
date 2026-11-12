ALTER TABLE persons ADD COLUMN seen_at TEXT;
ALTER TABLE persons ADD COLUMN merged_at TEXT;
CREATE INDEX persons_list_status ON persons (list_status);
CREATE INDEX persons_merged_into ON persons (merged_into);

ALTER TABLE claims ADD COLUMN first_seen_at TEXT;
ALTER TABLE claims ADD COLUMN rejected_at TEXT;
CREATE INDEX claims_rejected ON claims (rejected_at) WHERE rejected_at IS NOT NULL;

ALTER TABLE candidates ADD COLUMN hit_person_ids_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE candidates ADD COLUMN cut_reason TEXT;

CREATE TABLE not_same (
    person_id TEXT NOT NULL REFERENCES persons (id),
    other_person_id TEXT NOT NULL REFERENCES persons (id),
    at TEXT NOT NULL,
    PRIMARY KEY (person_id, other_person_id)
);
CREATE INDEX not_same_other ON not_same (other_person_id);

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    at TEXT NOT NULL,
    kind TEXT NOT NULL,
    person_id TEXT,
    other_person_id TEXT,
    search_id TEXT,
    rank INTEGER,
    section TEXT,
    import_id TEXT,
    claim_id TEXT,
    undoes TEXT,
    detail_json TEXT NOT NULL DEFAULT '{}',
    user_id TEXT
);
CREATE INDEX events_person ON events (person_id, at);
CREATE INDEX events_other_person ON events (other_person_id, at);
CREATE INDEX events_search ON events (search_id);

CREATE TABLE imports (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    uploaded_at TEXT NOT NULL,
    status TEXT NOT NULL,
    text TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    confirmed_at TEXT
);

-- Each stored resolve entry's hit ids, keyed by the entry's first person id, which is its candidate's person_id.
CREATE TEMP TABLE resolved_hits (
    search_id TEXT NOT NULL,
    person_id TEXT NOT NULL,
    hit_person_ids_json TEXT NOT NULL,
    PRIMARY KEY (search_id, person_id)
);
INSERT OR IGNORE INTO resolved_hits (search_id, person_id, hit_person_ids_json)
SELECT r.search_id, json_extract(e.value, '$.person_ids[0]'), json_extract(e.value, '$.hit_person_ids')
FROM step_runs r
JOIN step_payloads p ON p.step_run_id = r.id
JOIN json_each(p.output_json, '$.entries') e
WHERE r.step = 'resolve' AND r.status = 'ok' AND p.output_json IS NOT NULL
    AND json_extract(e.value, '$.person_ids[0]') IS NOT NULL
    AND json_type(e.value, '$.hit_person_ids') = 'array';
UPDATE candidates SET hit_person_ids_json = h.hit_person_ids_json
FROM resolved_hits h
WHERE h.search_id = candidates.search_id AND h.person_id = candidates.person_id;
DROP TABLE resolved_hits;
