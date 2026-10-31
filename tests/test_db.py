import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from fn import db
from tests.helpers import make_db


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
        bad = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, bad)
        bad.joinpath("002_bad.sql").write_text("CREATE TABLE half (x);\nNOT SQL;")
        with mock.patch.object(db, "MIGRATIONS", bad), self.assertRaises(sqlite3.OperationalError):
            store.migrate()
        self.assertIsNone(store.conn.execute("SELECT name FROM sqlite_master WHERE name = 'half'").fetchone())
        self.assertEqual([r[0] for r in store.conn.execute("SELECT version FROM schema_migrations")], [1])


class ClaimsFtsTest(unittest.TestCase):
    def test_tokenizer_stems_and_folds_diacritics(self):
        """claims_fts uses porter and unicode61 with diacritics removed, kept in sync by the insert trigger."""
        conn = make_db(self).conn
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'claims_fts'").fetchone()[0]
        self.assertIn("tokenize = 'porter unicode61 remove_diacritics 2'", sql)
        conn.execute("INSERT INTO persons VALUES ('p1', 'An Example', 'an example', 'candidate', NULL)")
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
