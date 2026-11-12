import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fn import db
from fn.contracts import Search
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
        self.assertEqual(store.migrate(), [6])
        found = dict(conn.execute("SELECT person_id, hit_person_ids_json FROM candidates").fetchall())
        self.assertEqual({p: json.loads(v) for p, v in found.items()}, {"p1": ["p1", "p2"], "p3": [], "p4": []})
        self.assertEqual([c.hit_person_ids for c in store.list_candidates("s1")], [["p1", "p2"], [], []])


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


if __name__ == "__main__":
    unittest.main()
