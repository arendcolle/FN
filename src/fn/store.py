"""All SQL in fn; one connection per thread."""
import hashlib
import json
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from fn import db
from fn.contracts import (
    CONTRACTS_VERSION,
    Candidate,
    ChipOrigin,
    Chips,
    Claim,
    ClaimDraft,
    Event,
    Identifier,
    IdentifierScheme,
    ImportRecord,
    ImportStatus,
    ListStatus,
    MatchFlag,
    NetworkFilter,
    Org,
    Person,
    RequestError,
    ScorePart,
    Search,
    SearchProgress,
    SearchStatus,
    Source,
    SourceKind,
    StepCall,
    StepRun,
    group_key,
    name_key,
)

STEP_COLUMNS = list(StepRun.model_fields)
CALL_COLUMNS = list(StepCall.model_fields)
PERSON_COLUMNS = list(Person.model_fields)
SOURCE_COLUMNS = list(Source.model_fields)
CLAIM_COLUMNS = [*(c for c in Claim.model_fields if c != "years"), "years_json"]
ORG_COLUMNS = list(Org.model_fields)
EVENT_COLUMNS = [*(c for c in Event.model_fields if c != "detail"), "detail_json"]
# Contact claims never make a person a search hit.
UNMATCHED_KINDS = ("email", "phone")


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _at(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _claim(row: dict) -> Claim:
    data = dict(row)
    return Claim.model_validate(data | {"years": json.loads(data.pop("years_json"))})


def _event(row: sqlite3.Row) -> Event:
    data = dict(row)
    return Event.model_validate(data | {"detail": json.loads(data.pop("detail_json"))})


def fold(value: str) -> str:
    """A claim value as the rejection rule compares it: trimmed and case-folded."""
    return value.strip().casefold()


def hidden_keys(claims: list[tuple[Claim, SourceKind]]) -> set[tuple[str, str, str]]:
    """The (person, kind, folded value) keys a rejected claim hides among one set of a person's claims.

    A key comes back to view when a staff claim of that value was first seen after its latest rejection.
    """
    rejected: dict[tuple[str, str, str], datetime] = {}
    for c, _ in claims:
        if c.rejected_at:
            key = (c.person_id, c.kind, fold(c.value))
            rejected[key] = max(rejected.get(key, c.rejected_at), c.rejected_at)
    retyped = {(c.person_id, c.kind, fold(c.value)): c.first_seen_at for c, kind in claims
               if kind == "staff" and not c.rejected_at and c.first_seen_at}
    return {key for key, at in rejected.items() if not (key in retyped and retyped[key] > at)}


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

    def list_searches(self, limit: int | None) -> list[Search]:
        """The newest searches of kind search first, at most limit of them, or all with None; jobs are left out."""
        rows = self.conn.execute("SELECT * FROM searches WHERE kind = 'search' ORDER BY created_at DESC LIMIT ?",
                                 (-1 if limit is None else limit,))
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

    def step_stat_rows(self, last: int) -> list[sqlite3.Row]:
        """One row per step run of the newest searches of kind search: step, status, seconds, cost_usd, calls."""
        return self.conn.execute(
            "SELECT s.step, s.status, round((julianday(s.ended_at) - julianday(s.started_at)) * 86400, 3) AS seconds, "
            "s.cost_usd, (SELECT count(*) FROM step_calls c WHERE c.step_run_id = s.id) AS calls "
            "FROM step_runs s WHERE s.search_id IN "
            "(SELECT id FROM searches WHERE kind = 'search' ORDER BY created_at DESC LIMIT ?)", (last,),
        ).fetchall()

    def search_stat_rows(self, last: int) -> list[sqlite3.Row]:
        """One row per newest search of kind search: id, question, status, seconds, cost_usd, people, first_seconds.

        first_seconds runs from the search's creation to the end of its first publish or save step with a count above 0.
        """
        return self.conn.execute(
            "SELECT s.id, s.question, s.status, round((julianday(s.finished_at) - julianday(s.created_at)) * 86400, 3) AS seconds, "
            "COALESCE((SELECT sum(cost_usd) FROM step_runs r WHERE r.search_id = s.id), 0) AS cost_usd, "
            "(SELECT count(*) FROM candidates c WHERE c.search_id = s.id) AS people, "
            "(SELECT round((julianday(min(r.ended_at)) - julianday(s.created_at)) * 86400, 3) FROM step_runs r "
            "JOIN step_payloads p ON p.step_run_id = r.id WHERE r.search_id = s.id AND r.step IN ('publish', 'save') "
            "AND json_extract(p.output_json, '$.count') > 0) AS first_seconds "
            "FROM searches s WHERE s.kind = 'search' ORDER BY s.created_at DESC LIMIT ?", (last,),
        ).fetchall()

    def search_decisions(self, last: int) -> list[tuple[Event, bool]]:
        """The add and skip events of the newest searches that have any, each with whether an undo reversed it."""
        rows = self.conn.execute(
            f"SELECT {', '.join('e.' + c for c in EVENT_COLUMNS)}, "
            "EXISTS (SELECT 1 FROM events u WHERE u.undoes = e.id) AS undone FROM events e "
            "WHERE e.kind IN ('add', 'skip') AND e.search_id IN "
            "(SELECT s.id FROM searches s WHERE s.id IN (SELECT search_id FROM events WHERE kind IN ('add', 'skip')) "
            "ORDER BY s.created_at DESC LIMIT ?) ORDER BY e.at, e.rowid", (last,),
        )
        return [(_event({k: r[k] for k in r.keys() if k != "undone"}), bool(r["undone"])) for r in rows]

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

    def failed_lanes(self, search_id: str) -> list[str]:
        """The names of the search's lane steps that ended in error, in step order."""
        rows = self.conn.execute(
            "SELECT step FROM step_runs WHERE search_id = ? AND step LIKE 'lane:%' AND status = 'error' ORDER BY seq",
            (search_id,),
        )
        return [r[0] for r in rows]

    def search_progress(self, search_id: str) -> SearchProgress | None:
        """The search's status, its saved people with no cut reason, and how many publish or save steps ended ok."""
        row = self.conn.execute(
            "SELECT status, "
            "(SELECT count(*) FROM candidates WHERE search_id = s.id AND cut_reason IS NULL) AS people, "
            "(SELECT count(*) FROM step_runs WHERE search_id = s.id AND step IN ('publish', 'save') "
            "AND status = 'ok') AS version FROM searches s WHERE id = ?",
            (search_id,),
        ).fetchone()
        return SearchProgress.model_validate(dict(row)) if row else None

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

    def upsert_claim(self, draft: ClaimDraft, at: datetime | None = None) -> Claim:
        """Store the claim and its source unless they are stored, and return it as stored.

        The id is the sha1 of person, kind, value, source and quote start; a stored claim with that id
        takes the draft's org_id, relation and years. A new claim gets first_seen_at at, else the current
        UTC time. Raises ValueError when the quote is not at its offsets in the source text as stored.
        """
        source = draft.source
        if source.text[draft.quote_start:draft.quote_end] != draft.quote or not draft.quote:
            raise ValueError(f"quote not at [{draft.quote_start}:{draft.quote_end}] of source {source.id}")
        key = "\0".join([draft.person_id, draft.kind, draft.value, source.id, str(draft.quote_start)])
        claim = Claim(id=hashlib.sha1(key.encode()).hexdigest(), source_id=source.id,
                      first_seen_at=at or datetime.now(UTC), **draft.model_dump(exclude={"source"}))
        with self.tx() as conn:
            self.upsert_source(source)
            data = claim.model_dump(exclude={"years"}) | {"years_json": json.dumps(claim.years),
                                                          "first_seen_at": _iso(claim.first_seen_at)}
            conn.execute(
                f"INSERT INTO claims ({', '.join(data)}) VALUES ({', '.join('?' * len(data))}) "
                "ON CONFLICT (id) DO UPDATE SET org_id = excluded.org_id, relation = excluded.relation, "
                "years_json = excluded.years_json WHERE org_id IS NOT excluded.org_id "
                "OR relation IS NOT excluded.relation OR years_json IS NOT excluded.years_json",
                list(data.values()),
            )
            row = conn.execute("SELECT first_seen_at, rejected_at FROM claims WHERE id = ?", (claim.id,)).fetchone()
        return claim.model_copy(update={"first_seen_at": _at(row[0]), "rejected_at": _at(row[1])})

    def upsert_org(self, org: Org, replace: bool) -> None:
        """Insert the org row; a stored row with its id is overwritten when replace is set, else kept."""
        data = org.model_dump()
        data["fetched_at"] = _iso(org.fetched_at)
        update = ", ".join(f"{k} = excluded.{k}" for k in data if k != "id")
        self.conn.execute(
            f"INSERT INTO orgs ({', '.join(data)}) VALUES ({', '.join('?' * len(data))}) "
            f"ON CONFLICT (id) DO {f'UPDATE SET {update}' if replace else 'NOTHING'}",
            list(data.values()),
        )

    def get_orgs(self, org_ids: list[str]) -> dict[str, Org]:
        rows = self.conn.execute(
            f"SELECT {', '.join(ORG_COLUMNS)} FROM orgs WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(org_ids),),
        )
        return {r["id"]: Org.model_validate(dict(r)) for r in rows}

    def match_claims(self, query: str, exclude: tuple[SourceKind, ...]) -> list[tuple[Person, Claim, float]]:
        """Every person with a claim matching the FTS5 query, from a source of no kind in exclude, best first.

        Each comes with its best claim and that claim's bm25, which is lower for a better match; equal scores
        are ordered by person id. Hidden claims, as claims_of hides them, and email and phone claims never match.
        """
        rows = self.conn.execute(
            "WITH m AS MATERIALIZED (SELECT rowid, bm25(claims_fts) AS score FROM claims_fts WHERE claims_fts MATCH ?) "
            f"SELECT {', '.join(f'p.{c} AS p_{c}' for c in PERSON_COLUMNS)}, "
            f"{', '.join(f'c.{c}' for c in CLAIM_COLUMNS)}, m.score AS best "
            "FROM m JOIN claims c ON c.rowid = m.rowid JOIN persons p ON p.id = c.person_id "
            "JOIN sources s ON s.id = c.source_id WHERE s.kind NOT IN (SELECT value FROM json_each(?)) "
            "AND c.rejected_at IS NULL AND c.kind NOT IN (SELECT value FROM json_each(?)) "
            "ORDER BY best, c.person_id, c.rowid",
            (query, json.dumps(exclude), json.dumps(UNMATCHED_KINDS)),
        )
        hidden = self._hidden_everywhere()
        found: dict[str, tuple[Person, Claim, float]] = {}
        for row in rows:
            data = dict(row)
            person = Person.model_validate({c: data.pop(f"p_{c}") for c in PERSON_COLUMNS})
            best, claim = data.pop("best"), _claim(data)
            key = (person.merged_into or person.id, claim.kind, fold(claim.value))
            if person.id not in found and key not in hidden:
                found[person.id] = (person, claim, best)
        return list(found.values())

    def _hidden_everywhere(self) -> set[tuple[str, str, str]]:
        """hidden_keys over the whole persons of every record with a rejected claim."""
        rows = self.conn.execute(
            "SELECT DISTINCT COALESCE(p.merged_into, p.id) FROM claims c JOIN persons p ON p.id = c.person_id "
            "WHERE c.rejected_at IS NOT NULL"
        )
        return hidden_keys(self._person_claims([r[0] for r in rows]))

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

    def _person_claims(self, person_ids: list[str]) -> list[tuple[Claim, SourceKind]]:
        """Every claim of each id's whole person and its source kind, under the canonical id, by person, kind, value.

        A claim of a merged record counts as first seen at the later of its own time and the merge.
        """
        rows = self.conn.execute(
            "WITH asked AS (SELECT DISTINCT COALESCE(merged_into, id) AS id FROM persons "
            "WHERE id IN (SELECT value FROM json_each(?))), "
            "records AS (SELECT p.id, a.id AS canonical, p.merged_at FROM asked a JOIN persons p ON p.id = a.id "
            "UNION ALL SELECT p.id, a.id, p.merged_at FROM asked a JOIN persons p ON p.merged_into = a.id) "
            f"SELECT {', '.join(f'c.{c}' for c in CLAIM_COLUMNS if c != 'person_id')}, r.canonical AS person_id, "
            "r.merged_at, s.kind AS source_kind FROM records r JOIN claims c ON c.person_id = r.id "
            "JOIN sources s ON s.id = c.source_id ORDER BY r.canonical, c.kind, c.value",
            (json.dumps(person_ids),),
        )
        found = []
        for row in rows:
            data = dict(row)
            merged_at, kind = data.pop("merged_at"), data.pop("source_kind")
            if merged_at and (not data["first_seen_at"] or _at(merged_at) > _at(data["first_seen_at"])):
                data["first_seen_at"] = merged_at
            found.append((_claim(data), kind))
        return found

    def claims_of(self, person_ids: list[str], include_hidden: bool = False) -> list[Claim]:
        """Every claim of each id's whole person, once, with person_id the canonical id, by person, kind and value.

        Without include_hidden, a rejected claim and the claims of its person with the same kind and folded value
        are left out, unless a staff claim of that value was first seen after the rejection.
        """
        claims = self._person_claims(person_ids)
        if include_hidden:
            return [c for c, _ in claims]
        hidden = hidden_keys(claims)
        return [c for c, _ in claims if not c.rejected_at and (c.person_id, c.kind, fold(c.value)) not in hidden]

    def get_claim(self, claim_id: str) -> Claim | None:
        row = self.conn.execute(f"SELECT {', '.join(CLAIM_COLUMNS)} FROM claims WHERE id = ?", (claim_id,)).fetchone()
        return _claim(row) if row else None

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
                "reason_claim_ids_json, score_parts_json, hit_person_ids_json, cut_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(search_id, c.person_id, json.dumps(c.person_ids), c.section, c.rank, c.score,
                  json.dumps(c.lane_ranks), json.dumps(c.reason_claim_ids),
                  json.dumps([p.model_dump() for p in c.score_parts]), json.dumps(c.hit_person_ids), c.cut_reason)
                 for c in candidates],
            )
            conn.executemany(
                "INSERT INTO match_flags (search_id, person_id, other_person_id, reason, shared_fact) "
                "VALUES (?, ?, ?, ?, ?)",
                [(search_id, f.person_id, f.other_person_id, f.reason, f.shared_fact) for f in flags],
            )
        return len(candidates)

    def list_candidates(self, search_id: str, kept_only: bool = False) -> list[Candidate]:
        """The search's candidates, section network first, kept before cut within a section, then by rank.

        kept_only leaves out the cut ones.
        """
        rows = self.conn.execute(
            "SELECT * FROM candidates WHERE search_id = ?" + (" AND cut_reason IS NULL" if kept_only else "")
            + " ORDER BY section = 'new', cut_reason IS NOT NULL, rank", (search_id,)
        )
        return [
            Candidate(
                search_id=r["search_id"], person_id=r["person_id"], person_ids=json.loads(r["person_ids_json"]),
                section=r["section"], rank=r["rank"], score=r["score"], lane_ranks=json.loads(r["lane_ranks_json"]),
                reason_claim_ids=json.loads(r["reason_claim_ids_json"]),
                score_parts=[ScorePart.model_validate(p) for p in json.loads(r["score_parts_json"])],
                hit_person_ids=json.loads(r["hit_person_ids_json"]), cut_reason=r["cut_reason"],
            )
            for r in rows
        ]

    def count_candidates(self, search_ids: list[str]) -> dict[str, int]:
        """The number of kept candidates of each search that has any, by search id."""
        rows = self.conn.execute(
            "SELECT search_id, count(*) FROM candidates WHERE search_id IN (SELECT value FROM json_each(?)) "
            "AND cut_reason IS NULL GROUP BY search_id", (json.dumps(search_ids),),
        )
        return {r[0]: r[1] for r in rows}

    def list_flags(self, search_id: str) -> list[MatchFlag]:
        rows = self.conn.execute(
            "SELECT person_id, other_person_id, reason, shared_fact FROM match_flags WHERE search_id = ?", (search_id,)
        )
        return [MatchFlag.model_validate(dict(r)) for r in rows]

    def canonical_ids(self, person_ids: list[str]) -> dict[str, str]:
        """Each id to the id of the record it is merged into, else itself; unknown ids are left out."""
        rows = self.conn.execute(
            "SELECT id, COALESCE(merged_into, id) FROM persons WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(person_ids),),
        )
        return {r[0]: r[1] for r in rows}

    def records_of(self, person_id: str) -> list[Person]:
        """The canonical record of the id's person, then the records merged into it, by id."""
        rows = self.conn.execute(
            "WITH c AS (SELECT COALESCE(merged_into, id) AS id FROM persons WHERE id = ?) "
            f"SELECT {', '.join(f'p.{c}' for c in PERSON_COLUMNS)} FROM c JOIN persons p "
            "ON p.id = c.id OR p.merged_into = c.id ORDER BY p.merged_into IS NOT NULL, p.id",
            (person_id,),
        )
        return [Person.model_validate(dict(r)) for r in rows]

    def set_list_status(self, person_id: str, status: ListStatus) -> None:
        self.conn.execute("UPDATE persons SET list_status = ? WHERE id = ?", (status, person_id))

    def set_merged_into(self, person_id: str, into_id: str | None, at: datetime | None) -> None:
        self.conn.execute("UPDATE persons SET merged_into = ?, merged_at = ? WHERE id = ?",
                          (into_id, _iso(at), person_id))

    def set_seen(self, person_id: str, at: datetime) -> None:
        self.conn.execute("UPDATE persons SET seen_at = ? WHERE id = ?", (_iso(at), person_id))

    def set_claim_rejected(self, claim_id: str, at: datetime | None) -> None:
        self.conn.execute("UPDATE claims SET rejected_at = ? WHERE id = ?", (_iso(at), claim_id))

    def add_not_same(self, a: str, b: str, at: datetime) -> None:
        """Store the pair once, the smaller id first; a stored pair is kept."""
        self.conn.execute("INSERT OR IGNORE INTO not_same (person_id, other_person_id, at) VALUES (?, ?, ?)",
                          (min(a, b), max(a, b), _iso(at)))

    def remove_not_same(self, a: str, b: str) -> None:
        self.conn.execute("DELETE FROM not_same WHERE person_id = ? AND other_person_id = ?", (min(a, b), max(a, b)))

    def not_same_pairs(self, person_ids: list[str]) -> set[frozenset[str]]:
        """Every stored pair with one of the ids in it, as the record ids it was stored with."""
        rows = self.conn.execute(
            "WITH ids AS (SELECT value FROM json_each(?)) "
            "SELECT person_id, other_person_id FROM not_same WHERE person_id IN ids "
            "UNION SELECT person_id, other_person_id FROM not_same WHERE other_person_id IN ids",
            (json.dumps(person_ids),),
        )
        return {frozenset(r) for r in rows}

    def add_event(self, event: Event) -> None:
        row = event.model_dump(exclude={"detail"}) | {"at": _iso(event.at), "detail_json": json.dumps(event.detail)}
        self.conn.execute(
            f"INSERT INTO events ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values())
        )

    def get_event(self, event_id: str) -> Event | None:
        row = self.conn.execute(f"SELECT {', '.join(EVENT_COLUMNS)} FROM events WHERE id = ?", (event_id,)).fetchone()
        return _event(row) if row else None

    def events_of(self, person_id: str) -> list[Event]:
        """The events that name the id as person or other person, newest first."""
        rows = self.conn.execute(
            f"SELECT {', '.join(EVENT_COLUMNS)} FROM events WHERE rowid IN "
            "(SELECT rowid FROM events WHERE person_id = ?1 UNION SELECT rowid FROM events WHERE other_person_id = ?1) "
            "ORDER BY at DESC, rowid DESC",
            (person_id,),
        )
        return [_event(r) for r in rows]

    def network_by_group_key(self) -> dict[str, list[str]]:
        """The canonical ids of the people in the network, by the group key of their name, in id order."""
        found: dict[str, list[str]] = {}
        for key, person_id in self.conn.execute(
            "SELECT name_key, id FROM persons WHERE list_status = 'in_list' AND merged_into IS NULL ORDER BY id"
        ):
            found.setdefault(group_key(key), []).append(person_id)
        return found

    def list_network(self, flt: NetworkFilter, limit: int | None) -> tuple[list[str], int]:
        """The canonical ids of the network, newest added first, at most limit of them, and the total before the limit.

        The text matches, ignoring case, part of the name or of an affiliation, role, location or topic claim's value
        or organization name, over every record of the person; new_only keeps people with a fact first seen after
        seen_at, and import_id the people an event of that import names.
        """
        rows = self.conn.execute(
            "SELECT p.id FROM persons p WHERE p.list_status = 'in_list' AND p.merged_into IS NULL "
            "AND (?1 IS NULL OR p.id IN (SELECT COALESCE(r.merged_into, r.id) FROM events e JOIN persons r "
            "ON r.id IN (e.person_id, e.other_person_id) WHERE e.import_id = ?1)) "
            "AND (NOT ?2 OR p.seen_at IS NOT NULL AND EXISTS (SELECT 1 FROM persons r JOIN claims c ON c.person_id = r.id "
            "WHERE (r.id = p.id OR r.merged_into = p.id) AND c.rejected_at IS NULL "
            "AND MAX(COALESCE(c.first_seen_at, ''), COALESCE(r.merged_at, '')) > p.seen_at)) "
            "ORDER BY (SELECT MAX(e.at) FROM events e WHERE e.person_id = p.id AND e.kind = 'add') DESC NULLS LAST, p.id",
            (flt.import_id, flt.new_only),
        )
        ids = [r[0] for r in rows]
        if text := flt.text.strip().casefold():
            matching = self._network_matching(text) if ids else set()
            ids = [p for p in ids if p in matching]
        return ids[:limit] if limit is not None else ids, len(ids)

    def _network_matching(self, text: str) -> set[str]:
        """The canonical ids of the network people whose name or searchable claim contains the case-folded text."""
        rows = self.conn.execute(
            "WITH net AS (SELECT id, display_name FROM persons WHERE list_status = 'in_list' AND merged_into IS NULL), "
            "records AS (SELECT id AS canonical, id FROM net UNION ALL "
            "SELECT merged_into, id FROM persons WHERE merged_into IN (SELECT id FROM net)) "
            "SELECT id, display_name FROM net UNION ALL SELECT r.canonical, c.value FROM records r "
            "JOIN claims c ON c.person_id = r.id WHERE c.kind IN ('affiliation', 'role', 'location', 'topic') "
            "AND c.rejected_at IS NULL UNION ALL SELECT r.canonical, o.name FROM records r "
            "JOIN claims c ON c.person_id = r.id JOIN orgs o ON o.id = c.org_id "
            "WHERE c.kind = 'affiliation' AND c.rejected_at IS NULL"
        )
        return {r[0] for r in rows if r[1] and text in r[1].casefold()}

    def import_filename(self, import_id: str) -> str | None:
        row = self.conn.execute("SELECT filename FROM imports WHERE id = ?", (import_id,)).fetchone()
        return row[0] if row else None

    def identifiers_of(self, person_ids: list[str]) -> dict[str, list[Identifier]]:
        """The identifiers each record holds, by scheme and value; a record with none is left out."""
        rows = self.conn.execute(
            "SELECT person_id, scheme, value FROM person_identifiers "
            "WHERE person_id IN (SELECT value FROM json_each(?)) ORDER BY person_id, scheme, value",
            (json.dumps(person_ids),),
        )
        found: dict[str, list[Identifier]] = {}
        for r in rows:
            found.setdefault(r[0], []).append(Identifier(scheme=r[1], value=r[2]))
        return found

    def add_identifier(self, person_id: str, identifier: Identifier) -> bool:
        """Attach the identifier to the record; False when another record holds it."""
        with self.tx() as conn:
            conn.execute("INSERT OR IGNORE INTO person_identifiers (scheme, value, person_id) VALUES (?, ?, ?)",
                         (identifier.scheme, identifier.value, person_id))
            row = conn.execute("SELECT person_id FROM person_identifiers WHERE scheme = ? AND value = ?",
                               (identifier.scheme, identifier.value)).fetchone()
        return row[0] == person_id

    def remove_identifier(self, person_id: str, identifier: Identifier) -> None:
        self.conn.execute("DELETE FROM person_identifiers WHERE person_id = ? AND scheme = ? AND value = ?",
                          (person_id, identifier.scheme, identifier.value))

    # Imports: one row per uploaded file, its text and the summary of its row outcomes.
    def add_import(self, record: ImportRecord) -> None:
        self.conn.execute(
            "INSERT INTO imports (id, filename, uploaded_at, status, text, summary_json, confirmed_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (record.id, record.filename, _iso(record.uploaded_at), record.status, record.text,
             json.dumps(record.summary), _iso(record.confirmed_at)),
        )

    def get_import(self, import_id: str) -> ImportRecord | None:
        row = self.conn.execute(
            "SELECT id, filename, uploaded_at, status, text, summary_json, confirmed_at FROM imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        if row is None:
            return None
        data = dict(row)
        return ImportRecord.model_validate(data | {"summary": json.loads(data.pop("summary_json"))})

    def set_import(self, import_id: str, status: ImportStatus, summary: dict | None = None,
                   confirmed_at: datetime | None = None) -> None:
        """Set the import's status, and its summary and confirm time when given."""
        self.conn.execute(
            "UPDATE imports SET status = ?, summary_json = COALESCE(?, summary_json), "
            "confirmed_at = COALESCE(?, confirmed_at) WHERE id = ?",
            (status, json.dumps(summary) if summary is not None else None, _iso(confirmed_at), import_id),
        )
