"""Collector: fetch every source for a country, compare with what we stored, record changes.

    python -m civic_hub.collect --country ca          # all Canadian sources
    python -m civic_hub.collect --source ca-boc       # one source

First run of a source = baseline: values are stored but no "new" events are logged (otherwise
thousands of IRCC rows would flood the feed). Exit code 1 if any source failed (CronJob shows it).
"""
from __future__ import annotations

import argparse
import logging
import sys

from .sources import SOURCES, Source, by_country, canonical
from .store import DB, now

log = logging.getLogger("civic_hub")


def upsert_source(db: DB, s: Source):
    db.q("""INSERT INTO sources (id, name, country, category, url) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET name=excluded.name, country=excluded.country,
            category=excluded.category, url=excluded.url""", (s.id, s.name, s.country, s.category, s.url))


def collect_source(db: DB, s: Source, fetched=None) -> tuple[int, int]:
    """Returns (items_seen, changes_logged). `fetched` lets tests inject items."""
    t = now()
    items = fetched if fetched is not None else s.fetch()
    upsert_source(db, s)
    stored = {r["item_key"]: r for r in db.rows(
        "SELECT item_key, value, number, removed FROM items WHERE source_id=%s", (s.id,))}
    baseline = not stored
    changes = 0
    seen = set()

    def change(kind, it_key, title, url, old_v, new_v, old_n, new_n):
        nonlocal changes
        changes += 1
        db.q("""INSERT INTO changes (source_id,item_key,title,url,change_type,old_value,new_value,old_number,new_number,detected_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (s.id, it_key, title, url, kind, old_v, new_v, old_n, new_n, db.ts(t)))

    for it in items:
        if it.key in seen:
            continue
        seen.add(it.key)
        v = canonical(it.value)
        old = stored.get(it.key)
        if old is None:
            db.q("""INSERT INTO items (source_id,item_key,title,url,value,number,first_seen,last_seen,last_changed,removed)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,FALSE)""",
                 (s.id, it.key, it.title, it.url, v, it.number, db.ts(t), db.ts(t), db.ts(t)))
            db.q("INSERT INTO observations VALUES (%s,%s,%s,%s,%s)", (s.id, it.key, db.ts(t), v, it.number))
            if not baseline:
                change("new", it.key, it.title, it.url, None, v, None, it.number)
        elif old["value"] != v or old["removed"]:
            db.q("""UPDATE items SET title=%s,url=%s,value=%s,number=%s,last_seen=%s,last_changed=%s,removed=FALSE
                    WHERE source_id=%s AND item_key=%s""", (it.title, it.url, v, it.number, db.ts(t), db.ts(t), s.id, it.key))
            db.q("INSERT INTO observations VALUES (%s,%s,%s,%s,%s)", (s.id, it.key, db.ts(t), v, it.number))
            change("changed" if not old["removed"] else "returned", it.key, it.title, it.url,
                   old["value"], v, old["number"], it.number)
        else:
            db.q("UPDATE items SET last_seen=%s WHERE source_id=%s AND item_key=%s", (db.ts(t), s.id, it.key))

    if s.track_removed and items:
        for k, old in stored.items():
            if k not in seen and not old["removed"]:
                db.q("UPDATE items SET removed=TRUE, last_changed=%s WHERE source_id=%s AND item_key=%s", (db.ts(t), s.id, k))
                title = db.rows("SELECT title,url FROM items WHERE source_id=%s AND item_key=%s", (s.id, k))[0]
                change("removed", k, title["title"], title["url"], old["value"], None, old["number"], None)
    return len(seen), changes


def run(db: DB, sources: list[Source]) -> bool:
    db.migrate()
    all_ok = True
    for s in sources:
        started = now()
        try:
            n, c = collect_source(db, s)
            db.q("INSERT INTO runs (source_id,started_at,finished_at,ok,items,changes) VALUES (%s,%s,%s,TRUE,%s,%s)",
                 (s.id, db.ts(started), db.ts(now()), n, c))
            db.commit()
            log.info("%-20s ok  items=%-5d changes=%d", s.id, n, c)
        except Exception as e:  # one broken source must not stop the others
            db.conn.rollback()
            all_ok = False
            db.q("INSERT INTO runs (source_id,started_at,finished_at,ok,error) VALUES (%s,%s,%s,FALSE,%s)",
                 (s.id, db.ts(started), db.ts(now()), f"{type(e).__name__}: {e}"[:500]))
            db.commit()
            log.error("%-20s FAIL %s", s.id, e)
    return all_ok


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--country", default="ca")
    ap.add_argument("--source", help="run one source id")
    a = ap.parse_args(argv)
    srcs = [s for s in SOURCES if s.id == a.source] if a.source else by_country(a.country)
    if not srcs:
        sys.exit(f"no sources for {a.source or a.country}")
    sys.exit(0 if run(DB(), srcs) else 1)


if __name__ == "__main__":
    main()
