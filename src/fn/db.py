"""SQLite connections and numbered migrations."""
import sqlite3
from pathlib import Path

MIGRATIONS = Path(__file__).parent / "migrations"


def connect(path: Path) -> sqlite3.Connection:
    """Open one connection for the calling thread, creating its directory with mode 0700."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA secure_delete=ON")
    return conn


def migrate(conn: sqlite3.Connection) -> list[int]:
    """Apply every migration not yet in schema_migrations, each in its own transaction.

    Returns the versions applied. Foreign keys are off during a migration and
    checked with PRAGMA foreign_key_check before they are turned back on.
    """
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY)")
    done = {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for path in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        version = int(path.name[:3])
        if version in done:
            continue
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            conn.executescript(f"BEGIN;\n{path.read_text()}\nINSERT INTO schema_migrations (version) VALUES ({version});")
            broken = conn.execute("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise sqlite3.IntegrityError(f"migration {path.name} broke foreign keys: {[tuple(r) for r in broken]}")
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.execute("PRAGMA foreign_keys=ON")
        applied.append(version)
    return applied
