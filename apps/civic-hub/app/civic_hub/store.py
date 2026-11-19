"""Storage: PostgreSQL in the cluster, SQLite for local runs and tests.

Tables
  sources       one row per data source
  items         latest value of every tracked item (+ when first/last seen and last changed)
  changes       every new / changed / removed event  -> the "what changed" feed
  observations  value history (one row each time an item's value changes) -> charts
  runs          one row per collector run per source -> health dashboard
"""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
  id TEXT PRIMARY KEY, name TEXT NOT NULL, country TEXT NOT NULL, category TEXT NOT NULL, url TEXT
);
CREATE TABLE IF NOT EXISTS items (
  source_id TEXT NOT NULL, item_key TEXT NOT NULL, title TEXT NOT NULL, url TEXT,
  value TEXT NOT NULL, number DOUBLE PRECISION,
  first_seen {TS} NOT NULL, last_seen {TS} NOT NULL, last_changed {TS} NOT NULL, removed BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (source_id, item_key)
);
CREATE TABLE IF NOT EXISTS changes (
  id {PK}, source_id TEXT NOT NULL, item_key TEXT NOT NULL, title TEXT NOT NULL, url TEXT,
  change_type TEXT NOT NULL, old_value TEXT, new_value TEXT, old_number DOUBLE PRECISION, new_number DOUBLE PRECISION,
  detected_at {TS} NOT NULL
);
CREATE INDEX IF NOT EXISTS changes_detected ON changes (detected_at);
CREATE TABLE IF NOT EXISTS observations (
  source_id TEXT NOT NULL, item_key TEXT NOT NULL, observed_at {TS} NOT NULL, value TEXT NOT NULL, number DOUBLE PRECISION
);
CREATE INDEX IF NOT EXISTS observations_item ON observations (source_id, item_key, observed_at);
CREATE TABLE IF NOT EXISTS runs (
  id {PK}, source_id TEXT NOT NULL, started_at {TS} NOT NULL, finished_at {TS}, ok BOOLEAN NOT NULL DEFAULT FALSE,
  items INTEGER NOT NULL DEFAULT 0, changes INTEGER NOT NULL DEFAULT 0, error TEXT
);
"""


def now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


class DB:
    def __init__(self, url: str | None = None):
        url = url or os.environ.get("DATABASE_URL") or "sqlite:///civic-hub.db"
        self.sqlite = url.startswith("sqlite:")
        if self.sqlite:
            self.conn = sqlite3.connect(url.split("sqlite:///", 1)[1])
        else:
            import psycopg  # only needed in the cluster
            self.conn = psycopg.connect(url, autocommit=False)

    # -- helpers ---------------------------------------------------------
    def ts(self, d: datetime):
        return d.isoformat() if self.sqlite else d

    def q(self, sql: str, params: tuple = ()):
        if self.sqlite:
            sql = sql.replace("%s", "?")
        cur = self.conn.cursor()
        cur.execute(sql, params)
        return cur

    def rows(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = self.q(sql, params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]

    def commit(self):
        self.conn.commit()

    def migrate(self):
        ddl = SCHEMA.format(TS="TEXT" if self.sqlite else "TIMESTAMPTZ",
                            PK="INTEGER PRIMARY KEY AUTOINCREMENT" if self.sqlite else "BIGSERIAL PRIMARY KEY")
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            self.q(stmt)
        self.commit()
