CREATE TABLE lookups (
    person_id TEXT NOT NULL REFERENCES persons (id),
    kind TEXT NOT NULL,
    verdict TEXT NOT NULL,
    detail TEXT NOT NULL,
    at TEXT NOT NULL,
    PRIMARY KEY (person_id, kind)
);
