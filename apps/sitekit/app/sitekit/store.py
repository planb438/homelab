"""Database layer. PostgreSQL in the cluster; SQLite for tests and quick local runs."""
import os, sqlite3, threading
from contextlib import contextmanager

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL DEFAULT '',
        role TEXT NOT NULL, pw_hash TEXT NOT NULL, active BOOLEAN NOT NULL DEFAULT TRUE,
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS invites (
        token TEXT PRIMARY KEY, role TEXT NOT NULL, note TEXT NOT NULL DEFAULT '',
        created_by INTEGER, expires TIMESTAMP NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS submissions (
        id SERIAL PRIMARY KEY, form TEXT NOT NULL, data TEXT NOT NULL, email TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'new', note TEXT NOT NULL DEFAULT '', ip TEXT NOT NULL DEFAULT '',
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS audit (
        id SERIAL PRIMARY KEY, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
        created TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
    """CREATE TABLE IF NOT EXISTS hits (
        key TEXT NOT NULL, at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)""",
]


class Store:
    def __init__(self, url: str):
        self.url = url
        self.sqlite = url.startswith("sqlite")
        self._lock = threading.Lock()
        if self.sqlite:
            path = url.split("///", 1)[1] if "///" in url else ":memory:"
            self._conn = sqlite3.connect(path, check_same_thread=False, detect_types=sqlite3.PARSE_DECLTYPES)
            self._conn.row_factory = sqlite3.Row
        else:
            import psycopg
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            self._pool = ConnectionPool(url, min_size=1, max_size=4, kwargs={"row_factory": dict_row, "autocommit": True})

    def _sql(self, q: str) -> str:
        if self.sqlite:
            q = q.replace("%s", "?").replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        return q

    @contextmanager
    def cursor(self):
        if self.sqlite:
            with self._lock:
                cur = self._conn.cursor()
                try:
                    yield cur
                    self._conn.commit()
                finally:
                    cur.close()
        else:
            with self._pool.connection() as conn, conn.cursor() as cur:
                yield cur

    def run(self, q, args=()):
        with self.cursor() as c:
            c.execute(self._sql(q), args)

    def one(self, q, args=()):
        with self.cursor() as c:
            c.execute(self._sql(q), args)
            r = c.fetchone()
            return dict(r) if r else None

    def all(self, q, args=()):
        with self.cursor() as c:
            c.execute(self._sql(q), args)
            return [dict(r) for r in c.fetchall()]

    def migrate(self):
        for q in SCHEMA:
            self.run(q)


def from_env() -> Store:
    url = os.environ.get("DATABASE_URL", "sqlite:///:memory:")
    s = Store(url)
    s.migrate()
    return s
