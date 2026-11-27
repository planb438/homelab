"""Ask Authority Q&A, in the spirit of Question2Answer: public questions and answers, votes, best answer,
staff "Official answer" with a required official source, points and levels, tags and categories, search,
related questions, moderation queue for new members, flags, and a sitemap. Plain text only (no HTML from users)."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi import Request
from fastapi.responses import RedirectResponse, Response

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS qa_questions (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL,
        body TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', state TEXT NOT NULL DEFAULT 'visible', best_answer_id INTEGER,
        views INTEGER NOT NULL DEFAULT 0, score INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL, updated TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS qa_answers (id SERIAL PRIMARY KEY, question_id INTEGER NOT NULL, user_id INTEGER NOT NULL, body TEXT NOT NULL,
        official BOOLEAN NOT NULL DEFAULT FALSE, source_url TEXT NOT NULL DEFAULT '', state TEXT NOT NULL DEFAULT 'visible',
        score INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS qa_tags (question_id INTEGER NOT NULL, tag TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS qa_votes (user_id INTEGER NOT NULL, kind TEXT NOT NULL, target_id INTEGER NOT NULL, value INTEGER NOT NULL,
        PRIMARY KEY (user_id, kind, target_id))""",
    """CREATE TABLE IF NOT EXISTS qa_flags (user_id INTEGER NOT NULL, kind TEXT NOT NULL, target_id INTEGER NOT NULL, reason TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (user_id, kind, target_id))""",
    """CREATE TABLE IF NOT EXISTS qa_points (id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL, points INTEGER NOT NULL, reason TEXT NOT NULL,
        created TEXT NOT NULL)""",
]
POINTS = {"ask": 2, "answer": 4, "best_received": 15, "best_given": 3, "up_received": 5, "down_received": -2}
LEVELS = [(0, "Newcomer"), (20, "Member"), (100, "Helper"), (300, "Expert"), (1000, "Authority")]


def register(c):
    S, DB, esc, page, need = c.S, c.DB, c.esc, c.page, c.need
    cfg = {"categories": ["General"], "moderate_below": 10, "flags_to_hide": 3, "timezone": "America/Toronto",
           "intro": "Ask a question. Answers marked Official come from our team and link to an official source.",
           "official_domains": [], **S.module_config.get("qa", {})}
    TZ = ZoneInfo(cfg["timezone"])
    STAFF = set(S.staff_roles)
    DB.migrate(SCHEMA)
    c.NAV.extend([("Q&A", "/qa", None), ("Moderation", "/qa/moderate", STAFF)])
    app = c.app

    def stamp():
        return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

    def slug(t):
        return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")[:60] or "q"

    def points_of(uid):
        return DB.one("SELECT COALESCE(SUM(points), 0) AS p FROM qa_points WHERE user_id = %s", (uid,))["p"]

    def level(p):
        return [n for lim, n in LEVELS if p >= lim][-1]

    def award(uid, key, why):
        DB.run("INSERT INTO qa_points (user_id, points, reason, created) VALUES (%s, %s, %s, %s)", (uid, POINTS[key], f"{key}: {why}"[:200], stamp()))

    def text(body):
        out = esc(body)
        out = re.sub(r"(https?://[^\s<&]+)", r'<a href="\1" rel="nofollow ugc noopener" target="_blank">\1</a>', out)
        return out.replace("\n", "<br>")

    def viewer(request):
        user, t = c.current_user(request)
        return user, t, c.csrf_for(t)

    def is_staff(u):
        return bool(u) and u["role"] in STAFF

    def needs_review(u):
        return not is_staff(u) and points_of(u["id"]) < cfg["moderate_below"]

    def name_of(uid):
        u = DB.one("SELECT name, email FROM users WHERE id = %s", (uid,))
        return (u["name"] or u["email"].split("@")[0]) if u else "deleted"

    def okform(t, f):
        return bool(t) and c.check_csrf(t, f.get("csrf"))

    async def form(request):
        return {k: str(v).strip() for k, v in (await request.form()).items()}

    def qurl(q):
        return f"/qa/{q['id']}-{slug(q['title'])}"

    def qlist(rows):
        if not rows:
            return '<p class="muted">No questions here yet.</p>'
        out = ""
        for q in rows:
            n = DB.one("SELECT COUNT(*) AS n FROM qa_answers WHERE question_id = %s AND state = 'visible'", (q["id"],))["n"]
            off = DB.one("SELECT COUNT(*) AS n FROM qa_answers WHERE question_id = %s AND official = %s AND state = 'visible'", (q["id"], True))["n"]
            tags = " ".join(f'<a class="pill" href="/qa?tag={esc(t["tag"])}">{esc(t["tag"])}</a>' for t in DB.all("SELECT tag FROM qa_tags WHERE question_id = %s", (q["id"],)))
            badge = ' <span class="pill" style="background:#e3f6ec">Official answer</span>' if off else ""
            done = " ✓" if q["best_answer_id"] else ""
            out += f"""<div class="card" style="display:flex;gap:1rem"><div style="min-width:70px;text-align:center"><b>{q['score']}</b><div class="muted">votes</div>
<b>{n}{done}</b><div class="muted">answers</div></div><div><a href="{qurl(q)}"><b>{esc(q['title'])}</b></a>{badge}
<div class="muted">{esc(q['category'])} · asked by {esc(name_of(q['user_id']))} · {esc(q['created'])} · {q['views']} views</div><div>{tags}</div></div></div>"""
        return out

    @app.get("/qa")
    def home(request: Request, sort: str = "recent", cat: str = "", tag: str = "", q: str = ""):
        user, t, csrf = viewer(request)
        sql = "SELECT q.* FROM qa_questions q WHERE q.state = 'visible'"; a = []
        if cat:
            sql += " AND q.category = %s"; a.append(cat)
        if tag:
            sql += " AND q.id IN (SELECT question_id FROM qa_tags WHERE tag = %s)"; a.append(tag.lower())
        if q:
            for w in q.lower().split()[:5]:
                sql += " AND (LOWER(q.title) LIKE %s OR LOWER(q.body) LIKE %s)"; a += [f"%{w}%", f"%{w}%"]
        if sort == "unanswered":
            sql += " AND NOT EXISTS (SELECT 1 FROM qa_answers x WHERE x.question_id = q.id AND x.state = 'visible')"
        order = {"top": "q.score DESC, q.id DESC", "views": "q.views DESC"}.get(sort, "q.id DESC")
        rows = DB.all(f"{sql} ORDER BY {order} LIMIT 50", tuple(a))
        cats = " · ".join(f'<a href="/qa?cat={esc(x)}">{esc(x)}</a>' for x in cfg["categories"])
        sorts = " · ".join(f'<a href="/qa?sort={s}">{s}</a>' for s in ["recent", "top", "unanswered", "views"])
        hot = " ".join(f'<a class="pill" href="/qa?tag={esc(r["tag"])}">{esc(r["tag"])} ({r["n"]})</a>' for r in DB.all("SELECT t.tag, COUNT(*) AS n FROM qa_tags t JOIN qa_questions q ON q.id = t.question_id WHERE q.state = 'visible' GROUP BY t.tag ORDER BY n DESC LIMIT 15"))
        ask = '<a href="/qa/ask"><button>Ask a question</button></a>' if user else '<a href="/app/login?next=/qa/ask">Log in</a> or <a href="/app/signup?next=/qa/ask">create an account</a> to ask.'
        return page(f"{S.site_name} — Questions", f"""<p>{esc(cfg['intro'])}</p><p>{ask}</p>
<form method="get" class="card"><input name="q" value="{esc(q)}" placeholder="Search questions"></form>
<p>Sort: {sorts}</p><p>Categories: {cats}</p><p>{hot}</p>{qlist(rows)}<p class="muted"><a href="/qa/users">Top contributors</a></p>""", user, csrf)

    @app.get("/qa/ask")
    def ask_form(request: Request, err: str = ""):
        user, t, deny = need(request)
        if deny:
            return deny
        csrf = c.csrf_for(t)
        co = "".join(f"<option>{esc(x)}</option>" for x in cfg["categories"])
        msg = f'<p class="err">{esc(err)}</p>' if err else ""
        return page("Ask a question", f"""{msg}<form method="post" class="card"><input type="hidden" name="csrf" value="{csrf}">
<label>Question title (be specific)</label><input name="title" maxlength="150" required><label>Category</label><select name="category">{co}</select>
<label>Details</label><textarea name="body" rows="7" required></textarea><label>Tags (comma separated, up to 5)</label><input name="tags" placeholder="work permit, ircc">
<input name="website" style="display:none" tabindex="-1" autocomplete="off"><button>Post question</button></form>
<p class="muted">Don't post personal details like file numbers, passport numbers or addresses.</p>""", user, csrf)

    @app.post("/qa/ask")
    async def ask(request: Request):
        user, t, deny = need(request)
        if deny:
            return deny
        f = await form(request)
        if not okform(t, f) or f.get("website"):
            return RedirectResponse("/qa", 303)
        if c.limited(f"qa-ask:{user['id']}", 5, 60):
            return ask_form(request, "You've asked a lot this hour. Try again later.")
        title, body = f.get("title", "")[:150], f.get("body", "")[:8000]
        if len(title) < 15 or len(body) < 20 or f.get("category") not in cfg["categories"]:
            return ask_form(request, "Give a title of 15+ characters, some details, and pick a category.")
        if not is_staff(user) and len(re.findall(r"https?://", body)) > 2:
            return ask_form(request, "Too many links for a new question.")
        state = "pending" if needs_review(user) else "visible"
        qid = DB.one("INSERT INTO qa_questions (user_id, category, title, body, state, created, updated) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                     (user["id"], f["category"], title, body, state, stamp(), stamp()))["id"]
        for tg in {x.strip().lower()[:30] for x in f.get("tags", "").split(",") if x.strip()}.__iter__():
            if DB.one("SELECT COUNT(*) AS n FROM qa_tags WHERE question_id = %s", (qid,))["n"] < 5:
                DB.run("INSERT INTO qa_tags (question_id, tag) VALUES (%s, %s)", (qid, re.sub(r"[^a-z0-9 \-]", "", tg)))
        award(user["id"], "ask", f"q{qid}")
        c.audit(user["email"], "qa_ask", f"{qid} {state}")
        return RedirectResponse(f"/qa/{qid}-{slug(title)}" + ("?pending=1" if state == "pending" else ""), 303)

    def can_see(row, user):
        return row["state"] == "visible" or is_staff(user) or (user and row["user_id"] == user["id"] and row["state"] == "pending")

    @app.get("/qa/{qid:int}-{s}")
    def question(qid: int, s: str, request: Request, pending: int = 0):
        user, t, csrf = viewer(request)
        q = DB.one("SELECT * FROM qa_questions WHERE id = %s", (qid,))
        if not q or not can_see(q, user):
            return page("Not found", "<p>This question isn't available.</p>", user, csrf)
        DB.run("UPDATE qa_questions SET views = views + 1 WHERE id = %s", (qid,))
        ans = [a for a in DB.all("SELECT * FROM qa_answers WHERE question_id = %s ORDER BY official DESC, score DESC, id", (qid,)) if can_see(a, user)]
        best = q["best_answer_id"]
        ans.sort(key=lambda a: (a["id"] != best, not a["official"], -a["score"]))

        def votebox(kind, row):
            if not user or user["id"] == row["user_id"]:
                return f'<b>{row["score"]}</b>'
            return f"""<form method="post" action="/qa/vote" class="inline"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="kind" value="{kind}">
<input type="hidden" name="id" value="{row['id']}"><button class="link" name="value" value="1" title="Useful">▲</button> <b>{row['score']}</b>
<button class="link" name="value" value="-1" title="Not useful">▼</button></form>"""

        def flagbtn(kind, row):
            if not user or user["id"] == row["user_id"]:
                return ""
            return f'<form method="post" action="/qa/flag" class="inline"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="kind" value="{kind}"><input type="hidden" name="id" value="{row["id"]}"><button class="link">flag</button></form>'

        def staffbtns(kind, row):
            if not is_staff(user):
                return ""
            nxt = "hidden" if row["state"] == "visible" else "visible"
            return f'<form method="post" action="/qa/moderate/{kind}/{row["id"]}" class="inline"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="state" value="{nxt}"><button class="link">{"hide" if nxt == "hidden" else "show"}</button></form>'

        al = ""
        for a in ans:
            tags = []
            if a["official"]:
                tags.append('<span class="pill" style="background:#e3f6ec">Official answer</span>')
            if a["id"] == best:
                tags.append('<span class="pill" style="background:#fff3d6">Best answer</span>')
            if a["state"] != "visible":
                tags.append(f'<span class="pill">{esc(a["state"])}</span>')
            src = f'<p>Official source: <a href="{esc(a["source_url"])}" target="_blank" rel="noopener">{esc(a["source_url"])}</a></p>' if a["source_url"] else ""
            pick = ""
            if user and (user["id"] == q["user_id"] or is_staff(user)) and a["id"] != best and a["state"] == "visible":
                pick = f'<form method="post" action="/qa/best" class="inline"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="id" value="{a["id"]}"><button class="link">Select as best</button></form>'
            al += f"""<div class="card" style="display:flex;gap:1rem"><div style="min-width:60px;text-align:center">{votebox('a', a)}</div><div style="flex:1">{' '.join(tags)}
<p>{text(a['body'])}</p>{src}<div class="muted">{esc(name_of(a['user_id']))} ({level(points_of(a['user_id']))}) · {esc(a['created'])} {pick} {flagbtn('a', a)} {staffbtns('a', a)}</div></div></div>"""
        tags = " ".join(f'<a class="pill" href="/qa?tag={esc(x["tag"])}">{esc(x["tag"])}</a>' for x in DB.all("SELECT tag FROM qa_tags WHERE question_id = %s", (qid,)))
        related = DB.all("""SELECT DISTINCT q.* FROM qa_questions q JOIN qa_tags t ON t.question_id = q.id WHERE q.state = 'visible' AND q.id <> %s
            AND t.tag IN (SELECT tag FROM qa_tags WHERE question_id = %s) ORDER BY q.score DESC LIMIT 5""", (qid, qid))
        rel = "".join(f'<li><a href="{qurl(r)}">{esc(r["title"])}</a></li>' for r in related)
        if user:
            src = '<label>Official source link (required for official answers, e.g. canada.ca)</label><input name="source_url" placeholder="https://www.canada.ca/...">' if is_staff(user) else ""
            box = f"""<form method="post" action="/qa/{qid}/answer" class="card"><input type="hidden" name="csrf" value="{csrf}"><h2>Your answer</h2>
<textarea name="body" rows="6" required></textarea>{src}<input name="website" style="display:none" tabindex="-1" autocomplete="off"><button>Post answer</button></form>"""
        else:
            box = f'<p><a href="/app/login?next={qurl(q)}">Log in</a> or <a href="/app/signup?next={qurl(q)}">create an account</a> to answer.</p>'
        note = '<p class="ok">Thanks! New members\' posts are checked by our team before they appear.</p>' if pending or q["state"] == "pending" else ""
        closed = '<p class="muted">This question is closed.</p>' if q["status"] == "closed" else ""
        desc = esc(q["body"][:150].replace("\n", " "))
        return page(q["title"], f"""<meta name="description" content="{desc}">{note}<div class="card" style="display:flex;gap:1rem"><div style="min-width:60px;text-align:center">{votebox('q', q)}</div>
<div style="flex:1"><p>{text(q['body'])}</p><div>{tags}</div><div class="muted">{esc(q['category'])} · {esc(name_of(q['user_id']))} · {esc(q['created'])} · {q['views'] + 1} views {flagbtn('q', q)} {staffbtns('q', q)}</div></div></div>
<h2>{len(ans)} answer(s)</h2>{al}{closed}{'' if q['status'] == 'closed' else box}{f'<div class="card"><h2>Related questions</h2><ul>{rel}</ul></div>' if rel else ''}""", user, csrf)

    @app.post("/qa/{qid}/answer")
    async def answer(qid: int, request: Request):
        user, t, deny = need(request)
        if deny:
            return deny
        f = await form(request)
        q = DB.one("SELECT * FROM qa_questions WHERE id = %s", (qid,))
        if not okform(t, f) or f.get("website") or not q or q["status"] == "closed" or q["state"] != "visible":
            return RedirectResponse("/qa", 303)
        body = f.get("body", "")[:8000]
        if len(body) < 15 or c.limited(f"qa-ans:{user['id']}", 15, 60):
            return RedirectResponse(qurl(q), 303)
        official, src = False, ""
        if is_staff(user) and f.get("source_url"):
            src = f["source_url"][:300]
            doms = cfg["official_domains"]
            if not re.match(r"^https://[a-z0-9.-]+\.[a-z]{2,}(/|$)", src) or (doms and not any(re.match(rf"^https://([a-z0-9-]+\.)*{re.escape(d)}(/|$)", src) for d in doms)):
                return page("Source needed", f'<p class="err">Official answers need an https link to an official source{" (" + ", ".join(doms) + ")" if doms else ""}.</p><p><a href="{qurl(q)}">Back</a></p>', user, c.csrf_for(t))
            official = True
        state = "pending" if needs_review(user) else "visible"
        DB.run("INSERT INTO qa_answers (question_id, user_id, body, official, source_url, state, created) VALUES (%s, %s, %s, %s, %s, %s, %s)",
               (qid, user["id"], body, official, src, state, stamp()))
        DB.run("UPDATE qa_questions SET updated = %s WHERE id = %s", (stamp(), qid))
        award(user["id"], "answer", f"q{qid}")
        return RedirectResponse(qurl(q) + ("?pending=1" if state == "pending" else ""), 303)

    @app.post("/qa/vote")
    async def vote(request: Request):
        user, t, deny = need(request)
        if deny:
            return deny
        f = await form(request)
        kind, val = f.get("kind"), int(f.get("value", "0") or 0)
        table = {"q": "qa_questions", "a": "qa_answers"}.get(kind)
        if not okform(t, f) or not table or val not in (1, -1):
            return RedirectResponse("/qa", 303)
        tid = int(f.get("id", "0") or 0)
        row = DB.one(f"SELECT * FROM {table} WHERE id = %s", (tid,))
        if not row or row["user_id"] == user["id"] or row["state"] != "visible":
            return RedirectResponse("/qa", 303)
        old = DB.one("SELECT value FROM qa_votes WHERE user_id = %s AND kind = %s AND target_id = %s", (user["id"], kind, tid))
        if old and old["value"] == val:
            DB.run("DELETE FROM qa_votes WHERE user_id = %s AND kind = %s AND target_id = %s", (user["id"], kind, tid))
            delta = -val
        else:
            if old:
                DB.run("UPDATE qa_votes SET value = %s WHERE user_id = %s AND kind = %s AND target_id = %s", (val, user["id"], kind, tid))
            else:
                DB.run("INSERT INTO qa_votes (user_id, kind, target_id, value) VALUES (%s, %s, %s, %s)", (user["id"], kind, tid, val))
            delta = val - (old["value"] if old else 0)
            award(row["user_id"], "up_received" if val > 0 else "down_received", f"{kind}{tid}")
        DB.run(f"UPDATE {table} SET score = score + %s WHERE id = %s", (delta, tid))
        qid = row["id"] if kind == "q" else row["question_id"]
        q = DB.one("SELECT id, title FROM qa_questions WHERE id = %s", (qid,))
        return RedirectResponse(qurl(q), 303)

    @app.post("/qa/best")
    async def best(request: Request):
        user, t, deny = need(request)
        if deny:
            return deny
        f = await form(request)
        a = DB.one("SELECT * FROM qa_answers WHERE id = %s", (int(f.get("id", "0") or 0),))
        q = DB.one("SELECT * FROM qa_questions WHERE id = %s", (a["question_id"],)) if a else None
        if not okform(t, f) or not q or not (user["id"] == q["user_id"] or is_staff(user)) or a["state"] != "visible":
            return RedirectResponse("/qa", 303)
        DB.run("UPDATE qa_questions SET best_answer_id = %s WHERE id = %s", (a["id"], q["id"]))
        if a["user_id"] != q["user_id"]:
            award(a["user_id"], "best_received", f"a{a['id']}")
        if user["id"] == q["user_id"] and not DB.one("SELECT id FROM qa_points WHERE user_id = %s AND reason = %s", (user["id"], f"best_given: q{q['id']}")):
            award(user["id"], "best_given", f"q{q['id']}")
        return RedirectResponse(qurl(q), 303)

    @app.post("/qa/flag")
    async def flag(request: Request):
        user, t, deny = need(request)
        if deny:
            return deny
        f = await form(request)
        kind = f.get("kind"); table = {"q": "qa_questions", "a": "qa_answers"}.get(kind)
        if not okform(t, f) or not table:
            return RedirectResponse("/qa", 303)
        tid = int(f.get("id", "0") or 0)
        if not DB.one("SELECT 1 AS x FROM qa_flags WHERE user_id = %s AND kind = %s AND target_id = %s", (user["id"], kind, tid)):
            DB.run("INSERT INTO qa_flags (user_id, kind, target_id) VALUES (%s, %s, %s)", (user["id"], kind, tid))
        n = DB.one("SELECT COUNT(*) AS n FROM qa_flags WHERE kind = %s AND target_id = %s", (kind, tid))["n"]
        if n >= cfg["flags_to_hide"]:
            DB.run(f"UPDATE {table} SET state = 'flagged' WHERE id = %s AND state = 'visible'", (tid,))
        return page("Thanks", '<p>Thanks — our team will review it.</p><p><a href="/qa">Back to questions</a></p>', user, c.csrf_for(t))

    @app.get("/qa/moderate")
    def moderate(request: Request):
        user, t, deny = need(request, STAFF)
        if deny:
            return deny
        csrf = c.csrf_for(t)

        def rows(kind, table):
            out = ""
            for r in DB.all(f"SELECT * FROM {table} WHERE state IN ('pending', 'flagged') ORDER BY id"):
                title = r.get("title") or f"answer on question #{r['question_id']}"
                fl = DB.one("SELECT COUNT(*) AS n FROM qa_flags WHERE kind = %s AND target_id = %s", (kind, r["id"]))["n"]
                btn = lambda s, l: f'<form method="post" action="/qa/moderate/{kind}/{r["id"]}" class="inline"><input type="hidden" name="csrf" value="{csrf}"><input type="hidden" name="state" value="{s}"><button>{l}</button></form>'
                out += f'<tr><td><span class="pill">{esc(r["state"])}</span> {fl} flag(s)</td><td><b>{esc(title)}</b><p>{text(r["body"][:600])}</p><div class="muted">{esc(name_of(r["user_id"]))}</div></td><td>{btn("visible", "Approve")} {btn("hidden", "Reject")}</td></tr>'
            return out
        body = rows("q", "qa_questions") + rows("a", "qa_answers")
        return page("Moderation queue", f'<div class="card"><table>{body or "<tr><td>Nothing waiting.</td></tr>"}</table></div>', user, csrf)

    @app.post("/qa/moderate/{kind}/{tid}")
    async def moderate_set(kind: str, tid: int, request: Request):
        user, t, deny = need(request, STAFF)
        if deny:
            return deny
        f = await form(request)
        table = {"q": "qa_questions", "a": "qa_answers"}.get(kind)
        if not okform(t, f) or not table or f.get("state") not in ("visible", "hidden"):
            return RedirectResponse("/qa/moderate", 303)
        DB.run(f"UPDATE {table} SET state = %s WHERE id = %s", (f["state"], tid))
        if f["state"] == "visible":
            DB.run("DELETE FROM qa_flags WHERE kind = %s AND target_id = %s", (kind, tid))
        c.audit(user["email"], f"qa_{f['state']}", f"{kind}{tid}")
        return RedirectResponse("/qa/moderate", 303)

    @app.get("/qa/users")
    def leaders(request: Request):
        user, t, csrf = viewer(request)
        rows = DB.all("SELECT user_id, SUM(points) AS p FROM qa_points GROUP BY user_id ORDER BY p DESC LIMIT 25")
        tr = "".join(f'<tr><td>{i + 1}</td><td>{esc(name_of(r["user_id"]))}</td><td>{level(r["p"])}</td><td>{r["p"]}</td></tr>' for i, r in enumerate(rows))
        return page("Top contributors", f'<div class="card"><table><tr><th>#</th><th>Name</th><th>Level</th><th>Points</th></tr>{tr}</table></div><p class="muted">Points: ask +2, answer +4, best answer +15, upvote received +5.</p>', user, csrf)

    @app.get("/qa/sitemap.xml")
    def sitemap(request: Request):
        base = str(request.base_url).rstrip("/")
        urls = "".join(f"<url><loc>{base}{qurl(q)}</loc></url>" for q in DB.all("SELECT id, title FROM qa_questions WHERE state = 'visible' ORDER BY id DESC LIMIT 5000"))
        return Response(f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>', media_type="application/xml")
