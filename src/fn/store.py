"""All SQL in fn; one connection per thread."""
import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from fn import db
from fn.contracts import (
    CONTRACTS_VERSION,
    Candidate,
    ChipOrigin,
    Chips,
    Claim,
    ClaimDraft,
    Identifier,
    IdentifierScheme,
    MatchFlag,
    Person,
    RequestError,
    Search,
    SearchStatus,
    Source,
    SourceKind,
    StepCall,
    StepRun,
    TieLabel,
    group_key,
    name_key,
)

STEP_COLUMNS = list(StepRun.model_fields)
CALL_COLUMNS = list(StepCall.model_fields)
PERSON_COLUMNS = list(Person.model_fields)
SOURCE_COLUMNS = list(Source.model_fields)
CLAIM_COLUMNS = list(Claim.model_fields)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class Store:
    def __init__(self, path: Path):
        self.path = path
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = self._local.conn = db.connect(self.path)
        return conn

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    def migrate(self) -> list[int]:
        return db.migrate(self.conn)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """A write transaction; inside an open one it joins it, and the outer one commits or rolls back."""
        if self.conn.in_transaction:
            yield self.conn
            return
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    def create_search(self, search: Search) -> None:
        row = search.model_dump(exclude={"chips"})
        row |= {
            "chips_json": search.chips.model_dump_json() if search.chips else None,
            "created_at": _iso(search.created_at),
            "finished_at": _iso(search.finished_at),
            "contracts_version": CONTRACTS_VERSION,
        }
        self.conn.execute(
            f"INSERT INTO searches ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values())
        )

    @staticmethod
    def _search(row: sqlite3.Row) -> Search:
        data = dict(row)
        chips_json = data.pop("chips_json")
        data.pop("contracts_version")
        data["chips"] = Chips.model_validate_json(chips_json) if chips_json else None
        return Search.model_validate(data)

    def get_search(self, search_id: str) -> Search | None:
        row = self.conn.execute("SELECT * FROM searches WHERE id = ?", (search_id,)).fetchone()
        return self._search(row) if row else None

    def list_searches(self, limit: int) -> list[Search]:
        """The newest searches first, at most limit of them."""
        rows = self.conn.execute("SELECT * FROM searches ORDER BY created_at DESC LIMIT ?", (limit,))
        return [self._search(r) for r in rows]

    def set_search_status(
        self, search_id: str, status: SearchStatus, error: str | None = None, finished_at: datetime | None = None
    ) -> None:
        self.conn.execute(
            "UPDATE searches SET status = ?, error = ?, finished_at = ? WHERE id = ?",
            (status, error, _iso(finished_at), search_id),
        )

    def set_search_chips(self, search_id: str, chips: Chips, origin: ChipOrigin) -> None:
        self.conn.execute(
            "UPDATE searches SET chips_json = ?, chips_origin = ? WHERE id = ?",
            (chips.model_dump_json(), origin, search_id),
        )

    def next_step_seq(self, search_id: str) -> int:
        row = self.conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM step_runs WHERE search_id = ?", (search_id,))
        return row.fetchone()[0]

    def start_step(self, run: StepRun, input_json: str) -> None:
        """Insert the step row and its input payload before the step runs."""
        row = run.model_dump()
        row["started_at"] = _iso(run.started_at)
        row["ended_at"] = _iso(run.ended_at)
        with self.tx() as conn:
            conn.execute(
                f"INSERT INTO step_runs ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values())
            )
            conn.execute("INSERT INTO step_payloads (step_run_id, input_json) VALUES (?, ?)", (run.id, input_json))

    def finish_step(self, run: StepRun, output_json: str | None) -> None:
        """Write the step's final status and metrics, and its output payload when there is one."""
        row = run.model_dump(exclude={"id", "search_id", "seq", "step", "started_at", "input_model"})
        row["ended_at"] = _iso(run.ended_at)
        with self.tx() as conn:
            conn.execute(
                f"UPDATE step_runs SET {', '.join(f'{k} = ?' for k in row)} WHERE id = ?", [*row.values(), run.id]
            )
            conn.execute("UPDATE step_payloads SET output_json = ? WHERE step_run_id = ?", (output_json, run.id))

    def list_steps(self, search_id: str) -> list[StepRun]:
        rows = self.conn.execute(
            f"SELECT {', '.join(STEP_COLUMNS)} FROM step_runs WHERE search_id = ? ORDER BY seq", (search_id,)
        )
        return [StepRun.model_validate(dict(r)) for r in rows]

    def get_step(self, step_run_id: str) -> StepRun | None:
        row = self.conn.execute(
            f"SELECT {', '.join(STEP_COLUMNS)} FROM step_runs WHERE id = ?", (step_run_id,)
        ).fetchone()
        return StepRun.model_validate(dict(row)) if row else None

    def get_payload(self, step_run_id: str) -> tuple[str, str | None] | None:
        row = self.conn.execute(
            "SELECT input_json, output_json FROM step_payloads WHERE step_run_id = ?", (step_run_id,)
        ).fetchone()
        return (row[0], row[1]) if row else None

    def add_call(self, call: StepCall) -> None:
        row = call.model_dump()
        self.conn.execute(
            f"INSERT INTO step_calls ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values())
        )

    def list_calls(self, step_run_id: str) -> list[StepCall]:
        rows = self.conn.execute(
            f"SELECT {', '.join(CALL_COLUMNS)} FROM step_calls WHERE step_run_id = ? ORDER BY seq", (step_run_id,)
        )
        return [StepCall.model_validate(dict(r)) for r in rows]

    def add_request_error(self, error_id: str, route: str, traceback: str, at: datetime) -> None:
        self.conn.execute(
            "INSERT INTO request_errors (id, route, traceback, at) VALUES (?, ?, ?, ?)",
            (error_id, route, traceback, _iso(at)),
        )

    def list_request_errors(self) -> list[RequestError]:
        rows = self.conn.execute("SELECT id, route, traceback, at FROM request_errors ORDER BY at DESC")
        return [RequestError.model_validate(dict(r)) for r in rows]

    def sweep(self, boot_id: str, now: datetime) -> list[str]:
        """Mark queued or running searches from other boots, and their running steps, interrupted.

        Returns the ids of the searches it marked.
        """
        with self.tx() as conn:
            ids = [
                r[0] for r in conn.execute(
                    "SELECT id FROM searches WHERE status IN ('queued', 'running') AND boot_id != ?", (boot_id,)
                )
            ]
            for search_id in ids:
                conn.execute(
                    "UPDATE searches SET status = 'interrupted', finished_at = ? WHERE id = ?", (_iso(now), search_id)
                )
                conn.execute(
                    "UPDATE step_runs SET status = 'interrupted', ended_at = ? WHERE search_id = ? AND status = 'running'",
                    (_iso(now), search_id),
                )
        return ids

    def resolve_person(self, identifiers: list[Identifier], display_name: str) -> Person:
        """The person holding any of the identifiers, else a new candidate; every identifier is then attached to it.

        An identifier already held by another person stays with that person. Raises ValueError with no identifiers.
        """
        if not identifiers:
            raise ValueError(f"resolve_person needs an identifier for {display_name!r}")
        with self.tx() as conn:
            row = None
            for ident in identifiers:
                row = conn.execute(
                    f"SELECT {', '.join(f'p.{c}' for c in PERSON_COLUMNS)} FROM person_identifiers i "
                    "JOIN persons p ON p.id = i.person_id WHERE i.scheme = ? AND i.value = ?",
                    (ident.scheme, ident.value),
                ).fetchone()
                if row:
                    break
            if row:
                person = Person.model_validate(dict(row))
            else:
                person = Person(id=str(uuid.uuid4()), display_name=display_name, name_key=name_key(display_name))
                conn.execute(
                    "INSERT INTO persons (id, display_name, name_key, list_status) VALUES (?, ?, ?, ?)",
                    (person.id, person.display_name, person.name_key, person.list_status),
                )
            conn.executemany(
                "INSERT OR IGNORE INTO person_identifiers (scheme, value, person_id) VALUES (?, ?, ?)",
                [(i.scheme, i.value, person.id) for i in identifiers],
            )
        return person

    def upsert_source(self, source: Source) -> None:
        """Insert the source unless its id is stored; raises ValueError when the stored text differs."""
        row = self.conn.execute("SELECT content_hash FROM sources WHERE id = ?", (source.id,)).fetchone()
        if row is not None:
            if row[0] != source.content_hash:
                raise ValueError(f"source {source.id} ({source.url}) is stored with other text; it needs a new id")
            return
        data = source.model_dump()
        data["fetched_at"] = _iso(source.fetched_at)
        self.conn.execute(
            f"INSERT INTO sources ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})", list(data.values())
        )

    def upsert_claim(self, draft: ClaimDraft) -> Claim:
        """Store the claim and its source unless they are stored, and return it.

        The id is the sha1 of person, kind, value, source and quote start. Raises ValueError when
        the quote is not at its offsets in the source text as stored.
        """
        source = draft.source
        if source.text[draft.quote_start:draft.quote_end] != draft.quote or not draft.quote:
            raise ValueError(f"quote not at [{draft.quote_start}:{draft.quote_end}] of source {source.id}")
        key = "\0".join([draft.person_id, draft.kind, draft.value, source.id, str(draft.quote_start)])
        claim = Claim(id=hashlib.sha1(key.encode()).hexdigest(), source_id=source.id,
                      **draft.model_dump(exclude={"source"}))
        with self.tx() as conn:
            self.upsert_source(source)
            data = claim.model_dump()
            conn.execute(
                f"INSERT OR IGNORE INTO claims ({', '.join(data)}) VALUES ({', '.join('?' * len(data))})",
                list(data.values()),
            )
        return claim

    def match_claims(self, query: str, exclude: SourceKind) -> list[tuple[Person, Claim, float]]:
        """Every person with a claim matching the FTS5 query, from a source not of kind exclude, best first.

        Each comes with its best claim and that claim's bm25, which is lower for a better match;
        ties are ordered by person id.
        """
        rows = self.conn.execute(
            "WITH m AS MATERIALIZED (SELECT rowid, bm25(claims_fts) AS score FROM claims_fts WHERE claims_fts MATCH ?) "
            f"SELECT {', '.join(f'p.{c} AS p_{c}' for c in PERSON_COLUMNS)}, "
            f"{', '.join(f'c.{c}' for c in CLAIM_COLUMNS)}, MIN(m.score) AS best "
            "FROM m JOIN claims c ON c.rowid = m.rowid JOIN persons p ON p.id = c.person_id "
            "JOIN sources s ON s.id = c.source_id WHERE s.kind != ? "
            "GROUP BY c.person_id ORDER BY best, c.person_id",
            (query, exclude),
        )
        found = []
        for row in rows:
            data = dict(row)
            person = Person.model_validate({c: data.pop(f"p_{c}") for c in PERSON_COLUMNS})
            best = data.pop("best")
            found.append((person, Claim.model_validate(data), best))
        return found

    def get_persons(self, person_ids: list[str]) -> dict[str, Person]:
        rows = self.conn.execute(
            f"SELECT {', '.join(PERSON_COLUMNS)} FROM persons WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(person_ids),),
        )
        return {r["id"]: Person.model_validate(dict(r)) for r in rows}

    def person_ids_by_group_key(self, keys: list[str]) -> dict[str, list[tuple[str, str]]]:
        """Every (person id, name key) per group key, in id order."""
        wanted: set[str] = set(keys)
        found: dict[str, list[tuple[str, str]]] = {}
        # group_key is not stored, so every person is read; a few thousand rows on one laptop.
        for key, person_id in self.conn.execute("SELECT name_key, id FROM persons ORDER BY id"):
            if (group := group_key(key)) in wanted:
                found.setdefault(group, []).append((person_id, key))
        return found

    def person_ids_by_identifier(self, scheme: IdentifierScheme, values: list[str]) -> dict[str, str]:
        """The person id holding each identifier value of the scheme; a value nobody holds is left out."""
        rows = self.conn.execute(
            "SELECT value, person_id FROM person_identifiers WHERE scheme = ? "
            "AND value IN (SELECT value FROM json_each(?))",
            (scheme, json.dumps(values)),
        )
        return {r[0]: r[1] for r in rows}

    def claims_of(self, person_ids: list[str]) -> list[Claim]:
        """Every claim of the persons, by person, kind and value."""
        rows = self.conn.execute(
            f"SELECT {', '.join(CLAIM_COLUMNS)} FROM claims WHERE person_id IN (SELECT value FROM json_each(?)) "
            "ORDER BY person_id, kind, value",
            (json.dumps(person_ids),),
        )
        return [Claim.model_validate(dict(r)) for r in rows]

    def get_claim(self, claim_id: str) -> Claim | None:
        row = self.conn.execute(f"SELECT {', '.join(CLAIM_COLUMNS)} FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return Claim.model_validate(dict(row)) if row else None

    def get_sources(self, source_ids: list[str]) -> dict[str, Source]:
        rows = self.conn.execute(
            f"SELECT {', '.join(SOURCE_COLUMNS)} FROM sources WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(source_ids),),
        )
        return {r["id"]: Source.model_validate(dict(r)) for r in rows}

    def save_candidates(self, search_id: str, candidates: list[Candidate], flags: list[MatchFlag]) -> int:
        """Replace the search's candidates and match flags in one transaction; returns the candidate count."""
        with self.tx() as conn:
            conn.execute("DELETE FROM candidates WHERE search_id = ?", (search_id,))
            conn.execute("DELETE FROM match_flags WHERE search_id = ?", (search_id,))
            conn.executemany(
                "INSERT INTO candidates (search_id, person_id, person_ids_json, section, rank, score, lane_ranks_json, "
                "reason_claim_ids_json, tie_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(search_id, c.person_id, json.dumps(c.person_ids), c.section, c.rank, c.score,
                  json.dumps(c.lane_ranks), json.dumps(c.reason_claim_ids), c.tie.model_dump_json())
                 for c in candidates],
            )
            conn.executemany(
                "INSERT INTO match_flags (search_id, person_id, other_person_id, reason, shared_fact) "
                "VALUES (?, ?, ?, ?, ?)",
                [(search_id, f.person_id, f.other_person_id, f.reason, f.shared_fact) for f in flags],
            )
        return len(candidates)

    def list_candidates(self, search_id: str) -> list[Candidate]:
        """The search's candidates, section network first, then by rank."""
        rows = self.conn.execute(
            "SELECT * FROM candidates WHERE search_id = ? ORDER BY section = 'new', rank", (search_id,)
        )
        return [
            Candidate(
                search_id=r["search_id"], person_id=r["person_id"], person_ids=json.loads(r["person_ids_json"]),
                section=r["section"], rank=r["rank"], score=r["score"], lane_ranks=json.loads(r["lane_ranks_json"]),
                reason_claim_ids=json.loads(r["reason_claim_ids_json"]),
                tie=TieLabel.model_validate_json(r["tie_json"]),
            )
            for r in rows
        ]

    def list_flags(self, search_id: str) -> list[MatchFlag]:
        rows = self.conn.execute(
            "SELECT person_id, other_person_id, reason, shared_fact FROM match_flags WHERE search_id = ?", (search_id,)
        )
        return [MatchFlag.model_validate(dict(r)) for r in rows]
