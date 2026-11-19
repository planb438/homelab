"""Public page + JSON API.

  /                 "What changed" page (last N days), latest indicators, IRCC times for one country
  /api/changes      ?days=7&source=ca-boc
  /api/items        ?source=ca-ircc-country&q=bahamas
  /healthz          liveness/readiness
"""
from __future__ import annotations

import html
import json
import os
import re
from datetime import timedelta

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse

from .store import DB, now

SITE_TITLE = os.environ.get("SITE_TITLE", "Ask Canada — Government Updates Tracker")
CREDIT_URL = os.environ.get("CREDIT_URL", "https://planb438.github.io/cloudkanata-site/")
DEFAULT_COUNTRY = os.environ.get("IRCC_COUNTRY", "Bahamas")

app = FastAPI(title="civic-hub", docs_url="/api/docs", redoc_url=None)
_db: DB | None = None


def db() -> DB:
    global _db
    if _db is None:
        _db = DB()
        _db.migrate()
    return _db


def _since(days: int):
    return db().ts(now() - timedelta(days=days))


def _changes(days: int, source: str | None = None, limit: int = 300):
    sql = """SELECT c.detected_at, c.source_id, s.name AS source, c.title, c.url, c.change_type,
                    c.old_value, c.new_value, c.old_number, c.new_number
             FROM changes c JOIN sources s ON s.id = c.source_id WHERE c.detected_at >= %s"""
    params: list = [_since(days)]
    if source:
        sql += " AND c.source_id = %s"
        params.append(source)
    sql += " ORDER BY c.detected_at DESC, c.id DESC LIMIT %s"
    params.append(limit)
    return db().rows(sql, tuple(params))


@app.get("/healthz")
def healthz():
    db().rows("SELECT 1 AS ok")
    return {"ok": True}


@app.get("/api/changes")
def api_changes(days: int = Query(7, ge=1, le=365), source: str | None = None):
    return JSONResponse([{**r, "detected_at": str(r["detected_at"])} for r in _changes(days, source)])


@app.get("/api/items")
def api_items(source: str, q: str | None = None, limit: int = Query(200, le=2000)):
    sql = "SELECT item_key, title, url, value, number, last_changed FROM items WHERE source_id=%s AND removed=FALSE"
    params: list = [source]
    if q:
        sql += " AND lower(title) LIKE %s"
        params.append(f"%{q.lower()}%")
    sql += " ORDER BY title LIMIT %s"
    params.append(limit)
    return JSONResponse([{**r, "value": json.loads(r["value"]), "last_changed": str(r["last_changed"])}
                         for r in db().rows(sql, tuple(params))])


def _fmt(v: str | None) -> str:
    if v is None:
        return "—"
    try:
        x = json.loads(v)
    except ValueError:
        return html.escape(v)
    if isinstance(x, dict):
        if "value" in x:
            val = x["value"]
            if isinstance(val, float) and val.is_integer() and abs(val) >= 10000:
                val = f"{int(val):,}"
            return html.escape(f"{val} ({x.get('date') or x.get('period', '')})")
        return html.escape(", ".join(f"{k}: {val}" for k, val in x.items() if k != "teaser"))
    return html.escape(str(x))


CSS = """
:root{--ink:#14213d;--muted:#5c677d;--line:#e5e7eb;--accent:#c8102e;--bg:#fafafa}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:var(--bg)}
header{background:#fff;border-bottom:3px solid var(--accent);padding:20px 16px}
header h1{margin:0;font-size:1.4rem}header p{margin:4px 0 0;color:var(--muted)}
main{max-width:1000px;margin:0 auto;padding:16px}
section{background:#fff;border:1px solid var(--line);border-radius:10px;padding:16px;margin:16px 0}
h2{font-size:1.1rem;margin:0 0 10px}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:10px}
.card{border:1px solid var(--line);border-radius:8px;padding:10px}.card b{display:block;font-size:1.3rem}
.card span{color:var(--muted);font-size:.85rem}table{width:100%;border-collapse:collapse;font-size:.92rem}
td,th{text-align:left;padding:6px 4px;border-bottom:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600}
.tag{font-size:.75rem;padding:1px 6px;border-radius:9px;background:#eef2ff}.tag.changed{background:#fff4e5}.tag.removed{background:#fde8e8}
a{color:#1d4ed8}footer{max-width:1000px;margin:0 auto;padding:16px;color:var(--muted);font-size:.85rem}
form{margin:0 0 8px}input{padding:6px 8px;border:1px solid var(--line);border-radius:6px}
"""


@app.get("/", response_class=HTMLResponse)
def index(days: int = Query(7, ge=1, le=90), country: str = DEFAULT_COUNTRY):
    d = db()
    ind = d.rows("""SELECT i.title, i.value, i.url FROM items i WHERE i.source_id IN ('ca-boc','ca-statcan')
                    AND i.removed=FALSE ORDER BY i.source_id, i.title""")
    cards = "".join(f'<div class="card"><span>{html.escape(r["title"])}</span><b>{_fmt(r["value"]).split(" (")[0]}</b>'
                    f'<span>{_fmt(r["value"]).split(" (")[-1].rstrip(")")}</span></div>' for r in ind)
    ch = _changes(days)
    rows = "".join(
        f'<tr><td>{str(r["detected_at"])[:10]}</td><td>{html.escape(r["source"])}</td>'
        f'<td><a href="{html.escape(r["url"] or "#")}">{html.escape(r["title"])}</a></td>'
        f'<td><span class="tag {r["change_type"]}">{r["change_type"]}</span></td>'
        f'<td>{_fmt(r["old_value"]) if r["change_type"] != "new" else ""}'
        f'{" → " if r["change_type"] == "changed" else ""}{_fmt(r["new_value"]) if r["change_type"] != "removed" else ""}</td></tr>'
        for r in ch if r["source_id"] != "ca-gc-news")
    news = "".join(f'<li><a href="{html.escape(r["url"])}">{html.escape(r["title"])}</a> '
                   f'<span class="tag">{str(r["detected_at"])[:10]}</span></li>'
                   for r in ch if r["source_id"] == "ca-gc-news")[:20000]
    ircc = d.rows("""SELECT title, value FROM items WHERE source_id='ca-ircc-country' AND removed=FALSE
                     AND lower(title) LIKE %s ORDER BY title""", (f"%— {country.lower()}%",))
    ircc_in = d.rows("SELECT title, value FROM items WHERE source_id='ca-ircc-incanada' AND removed=FALSE ORDER BY title")
    last = d.rows("SELECT max(finished_at) AS t FROM runs WHERE ok=TRUE")[0]["t"]
    def trow(r):
        label = r["title"]
        label = re.sub(r" — [^(]+?(?= \(|$)", "", label)
        return f'<tr><td>{html.escape(label)}</td><td>{_fmt(r["value"])}</td></tr>'
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(SITE_TITLE)}</title><style>{CSS}</style></head>
<body><header><h1>{html.escape(SITE_TITLE)}</h1>
<p>Official Government of Canada data, checked automatically. Last check: {str(last)[:16] if last else "not yet"} UTC</p></header><main>
<section><h2>Key numbers</h2><div class="cards">{cards or "<p>Waiting for first data run.</p>"}</div></section>
<section><h2>What changed — last {days} days ({len(ch)})</h2>
<p><a href="?days=1&country={html.escape(country)}">1 day</a> · <a href="?days=7&country={html.escape(country)}">7 days</a> · <a href="?days=30&country={html.escape(country)}">30 days</a></p>
<table><tr><th>Date</th><th>Source</th><th>Item</th><th></th><th>Old → new</th></tr>{rows or '<tr><td colspan="5">No changes in this period.</td></tr>'}</table></section>
<section><h2>IRCC processing times</h2><form><input name="country" value="{html.escape(country)}" aria-label="Country"> <button>Show</button></form>
<table><tr><th>Applying from {html.escape(country)}</th><th>Time</th></tr>{"".join(map(trow, ircc)) or '<tr><td colspan="2">No match.</td></tr>'}</table>
<table style="margin-top:12px"><tr><th>Applying inside Canada</th><th>Time</th></tr>{"".join(map(trow, ircc_in))}</table></section>
<section><h2>New on Canada.ca</h2><ul>{news or "<li>No new items in this period.</li>"}</ul></section>
</main><footer>Sources: IRCC, Canada.ca News Centre, Statistics Canada, Bank of Canada, open.canada.ca. Contains information licensed under the
<a href="https://open.canada.ca/en/open-government-licence-canada">Open Government Licence – Canada</a>. Not an official Government of Canada website;
always confirm on canada.ca before acting. · API: <a href="/api/docs">/api/docs</a><br>Built by <a href="{html.escape(CREDIT_URL)}">CloudKanata</a></footer></body></html>"""
    return HTMLResponse(page)
