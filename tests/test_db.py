import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from fn import db, evidence
from fn.contracts import Candidate, CardFit, Chips, ClaimDraft, Identifier, Org, Question, Search, Source
from fn.store import Store
from fn.worker import now
from tests.helpers import make_db, make_settings


class MigrateTest(unittest.TestCase):
    def test_second_migrate_changes_nothing(self):
        """A migrated database is left byte-for-byte alone by another migrate()."""
        store = make_db(self)
        schema = store.conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        before = store.conn.total_changes
        self.assertEqual(store.migrate(), [])
        self.assertEqual(store.conn.total_changes, before)
        self.assertEqual(store.conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall(), schema)

    def test_connection_pragmas(self):
        """Every connection has WAL, foreign keys, a busy timeout and secure delete."""
        conn = make_db(self).conn
        self.assertEqual(conn.execute("PRAGMA journal_mode").fetchone()[0], "wal")
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 5000)
        self.assertEqual(conn.execute("PRAGMA secure_delete").fetchone()[0], 1)

    def test_failed_migration_rolls_back(self):
        """A migration that fails leaves no tables and no version behind."""
        store = make_db(self)
        versions = [r[0] for r in store.conn.execute("SELECT version FROM schema_migrations")]
        bad = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bad)
        bad.joinpath(f"{max(versions) + 1:03d}_bad.sql").write_text("CREATE TABLE half (x);\nNOT SQL;")
        with mock.patch.object(db, "MIGRATIONS", bad), self.assertRaises(sqlite3.OperationalError):
            store.migrate()
        self.assertIsNone(store.conn.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchone())
        self.assertEqual([r[0] for r in store.conn.execute("SELECT version FROM schema_migrations")], versions)


class NetworkMigrationTest(unittest.TestCase):
    def test_006_fills_hit_ids_from_the_stored_resolve_output(self):
        """Each stored candidate gets the hit ids of the resolve entry whose first person is its person.

        A candidate with no matching entry, or an entry stored without hit ids, keeps '[]'.
        """
        store = Store(make_settings(self).db_path)
        self.addCleanup(store.close)
        old = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, old)
        for path in sorted(db.MIGRATIONS.glob("00[1-5]_*.sql")):
            shutil.copy(path, old / path.name)
        with mock.patch.object(db, "MIGRATIONS", old):
            store.migrate()
        conn = store.conn
        store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None,
                                   dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        for p in ("p1", "p2", "p3", "p4"):
            conn.execute("INSERT INTO persons (id, display_name, name_key, list_status) VALUES (?, ?, ?, 'candidate')",
                         (p, p, p))
        entries = [{"name_key": "a", "person_ids": ["p1", "p2"], "hit_person_ids": ["p1", "p2"], "lane_ranks": {}},
                   {"name_key": "b", "person_ids": ["p3"], "lane_ranks": {}}]
        conn.execute("INSERT INTO step_runs (id, search_id, seq, step, status, started_at, input_model, "
                     "contracts_version) VALUES ('r1', 's1', 1, 'resolve', 'ok', '2026-11-02', 'ResolveIn', '2')")
        conn.execute("INSERT INTO step_payloads (step_run_id, input_json, output_json) VALUES ('r1', '{}', ?)",
                     (json.dumps({"entries": entries, "flags": []}),))
        for p in ("p1", "p3", "p4"):
            conn.execute("INSERT INTO candidates (search_id, person_id, person_ids_json, section, rank, score, "
                         "lane_ranks_json, reason_claim_ids_json, score_parts_json) "
                         "VALUES ('s1', ?, '[]', 'new', 1, 0.1, '{}', '[]', '[]')", (p,))
        self.assertEqual(store.migrate(), [6, 7, 8, 9, 10, 11, 12, 13, 14])
        found = dict(conn.execute("SELECT person_id, hit_person_ids_json FROM candidates").fetchall())
        self.assertEqual({p: json.loads(v) for p, v in found.items()}, {"p1": ["p1", "p2"], "p3": [], "p4": []})
        self.assertEqual([c.hit_person_ids for c in store.list_candidates("s1")], [["p1", "p2"], [], []])

    def test_007_cuts_a_stored_openalex_only_candidate_without_belgian_years_and_nothing_else(self):
        """Migration 007 sets cut_reason by the ranker's rule over the stored columns; no rank changes, no row goes."""
        store = Store(make_settings(self).db_path)
        self.addCleanup(store.close)
        old = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, old)
        for path in sorted(db.MIGRATIONS.glob("00[1-6]_*.sql")):
            shutil.copy(path, old / path.name)
        with mock.patch.object(db, "MIGRATIONS", old):
            store.migrate()
        store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None,
                                   dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        belgian = json.dumps([{"feature": "belgian_years", "rank": 1, "points": 0.1, "claim_ids": [], "detail": "d"}])
        rows = [("cut", "new", '{"openalex": 1}', "[]"), ("years", "new", '{"openalex": 2}', belgian),
                ("two", "new", '{"openalex": 3, "web": 1}', "[]"), ("net", "network", '{"openalex": 4}', "[]")]
        for i, (p, section, lanes, parts) in enumerate(rows, 1):
            store.conn.execute("INSERT INTO persons (id, display_name, name_key, list_status) VALUES (?, ?, ?, 'candidate')",
                               (p, p, p))
            store.conn.execute("INSERT INTO candidates (search_id, person_id, person_ids_json, section, rank, score, "
                               "lane_ranks_json, reason_claim_ids_json, score_parts_json) "
                               "VALUES ('s1', ?, '[]', ?, ?, 0.1, ?, '[]', ?)", (p, section, i, lanes, parts))
        self.assertEqual(store.migrate(), [7, 8, 9, 10, 11, 12, 13, 14])
        found = {c.person_id: (c.rank, c.cut_reason) for c in store.list_candidates("s1")}
        self.assertEqual(found, {"cut": (1, "no_belgian_evidence"), "years": (2, None), "two": (3, None),
                                 "net": (4, None)})

    def test_kept_only_and_the_count_leave_out_cut_candidates_and_cut_ones_list_last(self):
        """list_candidates puts kept before cut in a section, kept_only drops the cut, count_candidates counts kept."""
        store = make_db(self)
        store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None,
                                   dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        for p in ("a", "b", "c"):
            store.conn.execute("INSERT INTO persons (id, display_name, name_key, list_status) VALUES (?, ?, ?, 'candidate')",
                               (p, p, p))
        store.save_candidates("s1", [
            Candidate(search_id="s1", person_id=p, person_ids=[p], section="new", rank=r, score=0.1,
                      lane_ranks={"openalex": 1}, cut_reason=reason)
            for p, r, reason in (("a", 1, "no_belgian_evidence"), ("b", 1, None), ("c", 2, None))], [])
        self.assertEqual([c.person_id for c in store.list_candidates("s1")], ["b", "c", "a"])
        self.assertEqual([c.person_id for c in store.list_candidates("s1", kept_only=True)], ["b", "c"])
        self.assertEqual(store.count_candidates(["s1"]), {"s1": 2})


class CandidateTierTest(unittest.TestCase):
    def test_012_adds_a_nullable_tier_and_fit_and_an_old_row_lists_with_none_for_both(self):
        """A saved candidate lists with its tier and fit; a row stored before 012 lists with None for both."""
        store = make_db(self)
        columns = {r["name"]: r["notnull"] for r in store.conn.execute("PRAGMA table_info(candidates)")}
        self.assertEqual((columns["tier"], columns["fit_json"]), (0, 0))
        store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None,
                                   dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        for p in ("a", "b"):
            store.conn.execute("INSERT INTO persons (id, display_name, name_key, list_status) VALUES (?, ?, ?, 'candidate')",
                               (p, p, p))
        fit = CardFit(tie_grade="medium", tie_claim_ids=["c1"], place="outside", role="met")
        store.save_candidates("s1", [Candidate(search_id="s1", person_id="a", person_ids=["a"], section="new", rank=1,
                                               score=0.1, lane_ranks={"seeds": 1}, tier=3, fit=fit)], [])
        store.conn.execute("INSERT INTO candidates (search_id, person_id, person_ids_json, section, rank, score, "
                           "lane_ranks_json, reason_claim_ids_json, score_parts_json) "
                           "VALUES ('s1', 'b', '[]', 'new', 2, 0.1, '{}', '[]', '[]')")
        self.assertEqual([(c.person_id, c.tier, c.fit) for c in store.list_candidates("s1")], [("a", 3, fit), ("b", None, None)])

    def test_013_stores_aside_and_an_old_row_lists_with_none(self):
        """A saved candidate lists with its aside group; a row stored without one lists with None."""
        store = make_db(self)
        store.create_search(Search(id="s1", question="q", status="done", created_at=now(), code_sha=None,
                                   dirty=False, llm_mode="replay", settings_json="{}", boot_id="b"))
        for p in ("a", "b"):
            store.conn.execute("INSERT INTO persons (id, display_name, name_key, list_status) VALUES (?, ?, ?, 'candidate')",
                               (p, p, p))
        store.save_candidates("s1", [Candidate(search_id="s1", person_id="a", person_ids=["a"], section="new", rank=1,
                                               score=0.1, lane_ranks={"seeds": 1}, tier=2, aside="outside")], [])
        store.conn.execute("INSERT INTO candidates (search_id, person_id, person_ids_json, section, rank, score, "
                           "lane_ranks_json, reason_claim_ids_json, score_parts_json) "
                           "VALUES ('s1', 'b', '[]', 'new', 2, 0.1, '{}', '[]', '[]')")
        self.assertEqual([(c.person_id, c.aside) for c in store.list_candidates("s1")], [("a", "outside"), ("b", None)])


class OrgMatchesTest(unittest.TestCase):
    def test_014_adds_the_org_matches_table_to_a_database_at_013(self):
        """A database at 013 has no org_matches table; migrate() applies 014 and the table takes a null org_id."""
        store = Store(make_settings(self).db_path)
        self.addCleanup(store.close)
        old = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, old)
        for path in db.MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"):
            if int(path.name[:3]) <= 13:
                shutil.copy(path, old / path.name)
        with mock.patch.object(db, "MIGRATIONS", old):
            store.migrate()
        self.assertEqual(store.conn.execute("SELECT name FROM sqlite_master WHERE name = 'org_matches'").fetchall(), [])
        self.assertEqual(store.migrate(), [14])
        store.save_org_answer("example institute", "Example Institute", None, now())
        self.assertEqual(store.org_answers(), {"example institute": None})


class ClaimsFtsTest(unittest.TestCase):
    def test_tokenizer_stems_and_folds_diacritics(self):
        """claims_fts uses porter and unicode61 with diacritics removed, kept in sync by the insert trigger."""
        conn = make_db(self).conn
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'claims_fts'").fetchone()[0]
        self.assertIn("tokenize = 'porter unicode61 remove_diacritics 2'", sql)
        conn.execute("INSERT INTO persons (id, display_name, name_key, list_status) "
                     "VALUES ('p1', 'An Example', 'an example', 'candidate')")
        conn.execute(
            "INSERT INTO sources (id, kind, url, text, content_hash, normalize_version)"
            " VALUES ('s1', 'record', 'https://example.org', 'Université libre, running models', 'h', 1)"
        )
        conn.execute(
            "INSERT INTO claims (id, person_id, kind, value, quote, quote_start, quote_end, source_id)"
            " VALUES ('c1', 'p1', 'affiliation', 'Université libre', 'running models', 18, 32, 's1')"
        )
        for term in ('"universite"', '"run"'):
            rows = conn.execute("SELECT rowid FROM claims_fts WHERE claims_fts MATCH ?", (term,)).fetchall()
            self.assertEqual(len(rows), 1, term)


class OrgsNearTest(unittest.TestCase):
    def test_an_org_in_the_box_is_returned_and_one_without_coordinates_or_beyond_it_is_not(self):
        """orgs_near gives the ids of the orgs with coordinates in the box, ordered by id."""
        store = make_db(self)
        store.upsert_source(Source(id="s1", kind="record", url="https://example.org/x", text="t", content_hash="s1"))
        for org_id, lat, lon in (("ror:0bbbbbb00", 42.4, -71.1), ("ror:0aaaaaa00", 42.3, -71.0),
                                 ("ror:0cccccc00", None, None), ("ror:0dddddd00", 48.8, 2.3)):
            store.upsert_org(Org(id=org_id, name=org_id, lat=lat, lon=lon, source_id="s1", fetched_at=now()), replace=True)
        self.assertEqual(store.orgs_near(42.36, -71.06, 30.0), ["ror:0aaaaaa00", "ror:0bbbbbb00"])


class SourceKindsTest(unittest.TestCase):
    def test_each_known_id_gives_its_kind_and_an_unknown_id_is_left_out(self):
        """source_kinds maps the ids the database holds to their kinds and omits the others."""
        store = make_db(self)
        for source_id, kind in (("s1", "record"), ("s2", "seed_page")):
            store.upsert_source(Source(id=source_id, kind=kind, url="https://example.org/x", text="t",
                                       content_hash=source_id))
        self.assertEqual(store.source_kinds(["s1", "s2", "nope"]), {"s1": "record", "s2": "seed_page"})
        self.assertEqual(store.source_kinds([]), {})


class RejectedDeathTest(unittest.TestCase):
    def test_a_rejected_death_claim_is_dropped_so_the_person_has_not_died(self):
        """claims_of leaves a rejected death claim out, so evidence reads no death."""
        store = make_db(self)
        text = "Died: June 20, 1966"
        source = Source(id="s1", kind="page", url="https://example.org/list", text=text, content_hash="s1")
        person = store.resolve_person([Identifier(scheme="mention", value="https://example.org/list#ann")], "Ann Example")
        claim = store.upsert_claim(ClaimDraft(person_id=person.id, kind="death", value="1966", quote=text, quote_start=0,
                                              quote_end=len(text), source=source, claim_date="1966", date_precision="year",
                                              date_method="stated_in_quote"))

        def died() -> str | None:
            card = {person.id: frozenset({"mention"})}
            return evidence.of(card, store.claims_of([person.id]), {}, Question(chips=Chips()), date(2026, 11, 17)).age.died

        self.assertEqual(died(), claim.id)
        store.set_claim_rejected(claim.id, now())
        self.assertIsNone(died())


if __name__ == "__main__":
    unittest.main()
