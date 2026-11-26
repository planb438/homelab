"""sitekit: serves a site's real files (synced from its Git repo) and adds a private /app area:
logins with roles, invite-only sign-up, public forms saved to PostgreSQL, a staff inbox and user admin."""
import html, json, os
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from . import config, store, security

S = config.from_env()
DB = store.from_env()
app = FastAPI(title=f"sitekit · {S.site_name}", docs_url=None, redoc_url=None, openapi_url=None)
COOKIE = "sk_session"
STAFF = {"admin", "staff"}
esc = html.escape


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def audit(actor, action, detail=""):
    DB.run("INSERT INTO audit (actor, action, detail) VALUES (%s, %s, %s)", (actor, action, detail[:500]))


def bootstrap_admin():
    if S.admin_email and S.admin_password and not DB.one("SELECT id FROM users WHERE role = %s", ("admin",)):
        DB.run("INSERT INTO users (email, name, role, pw_hash) VALUES (%s, %s, %s, %s)",
               (S.admin_email, "Admin", "admin", security.hash_password(S.admin_password)))
        audit("system", "bootstrap_admin", S.admin_email)


bootstrap_admin()


@app.middleware("http")
async def hide_git(request: Request, call_next):
    if request.url.path.startswith("/.git"):
        return PlainTextResponse("Not found", 404)
    return await call_next(request)


def current_user(request: Request):
    t = request.cookies.get(COOKIE)
    if not t:
        return None, None
    row = DB.one("SELECT u.id, u.email, u.name, u.role, u.active, s.expires FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = %s", (t,))
    if not row or not row["active"] or row["expires"] < now():
        return None, None
    return row, t


def client_ip(request: Request):
    return (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()


def limited(key: str, max_hits: int, minutes: int) -> bool:
    since = now() - timedelta(minutes=minutes)
    n = DB.one("SELECT COUNT(*) AS n FROM hits WHERE key = %s AND at > %s", (key, since))["n"]
    if n >= max_hits:
        return True
    DB.run("INSERT INTO hits (key, at) VALUES (%s, %s)", (key, now()))
    return False


def page(title, body, user=None, csrf=""):
    nav = ""
    if user:
        links = ['<a href="/app">Home</a>']
        if user["role"] in STAFF:
            links.append('<a href="/app/inbox">Inbox</a>')
        if user["role"] == "admin":
            links.append('<a href="/app/users">Users</a>')
        links.append('<a href="/app/account">My account</a>')
        links.append(f'<form method="post" action="/app/logout" class="inline"><input type="hidden" name="csrf" value="{csrf}"><button class="link">Log out</button></form>')
        nav = f'<nav>{"".join(links)}<span class="who">{esc(user["name"] or user["email"])} · {esc(user["role"])}</span></nav>'
    return HTMLResponse(f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>{esc(title)} · {esc(S.site_name)}</title>
<style>:root{{--c:{esc(S.color)}}}*{{box-sizing:border-box}}body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f5f7fa;color:#14202e}}
header{{background:var(--c);color:#fff;padding:.8rem 1.2rem;display:flex;gap:1rem;align-items:center}}header a{{color:#fff;text-decoration:none;font-weight:700}}
main{{max-width:980px;margin:1.2rem auto;padding:0 1rem}}nav{{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;margin-bottom:1rem}}nav .who{{margin-left:auto;color:#5b6b80;font-size:.9rem}}
.card{{background:#fff;border:1px solid #e3e8ef;border-radius:12px;padding:1rem 1.2rem;margin-bottom:.8rem}}label{{display:block;font-size:.85rem;color:#5b6b80;margin:.6rem 0 .2rem}}
input,select,textarea{{width:100%;padding:.55rem;border:1px solid #d5dbe3;border-radius:8px;font:inherit}}button{{background:var(--c);color:#fff;border:0;border-radius:8px;padding:.6rem 1rem;font:inherit;font-weight:600;cursor:pointer;margin-top:.8rem}}
button.link{{background:none;color:var(--c);padding:0;margin:0;font-weight:500}}.inline{{display:inline}}.err{{color:#a12626}}.ok{{color:#12805c}}table{{width:100%;border-collapse:collapse}}td,th{{text-align:left;padding:.45rem;border-bottom:1px solid #eef1f5;font-size:.92rem;vertical-align:top}}
.pill{{font-size:.75rem;background:#eef4fb;border-radius:6px;padding:.1rem .45rem}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.6rem}}.grid a{{display:block;background:#fff;border:1px solid #e3e8ef;border-radius:10px;padding:.8rem;text-decoration:none;color:inherit}}
.muted{{color:#5b6b80;font-size:.9rem}}</style></head>
<body><header><a href="/">{esc(S.site_name)}</a><span>· lab app</span></header><main>{nav}<h1>{esc(title)}</h1>{body}</main></body></html>""")


def need(request: Request, roles=None):
    user, t = current_user(request)
    if not user:
        return None, None, RedirectResponse("/app/login?next=" + request.url.path, 303)
    if roles and user["role"] not in roles:
        return None, None, page("Not allowed", '<p class="err">Your role can\'t open this page.</p>', user, security.csrf_for(S.secret_key, t))
    return user, t, None


def check_csrf(t, value):
    return bool(t) and value == security.csrf_for(S.secret_key, t)


@app.get("/healthz", response_class=PlainTextResponse)
def healthz():
    DB.one("SELECT 1 AS ok")
    return "ok"


@app.get("/app/login")
def login_form(next: str = "/app", err: str = ""):
    msg = f'<p class="err">{esc(err)}</p>' if err else ""
    return page("Log in", f"""{msg}<form method="post" class="card"><input type="hidden" name="next" value="{esc(next)}">
<label>Email</label><input name="email" type="email" autocomplete="username" required>
<label>Password</label><input name="password" type="password" autocomplete="current-password" required><button>Log in</button></form>
<p class="muted">No account? Ask an admin for an invite link.</p>""")


@app.post("/app/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), next: str = Form("/app")):
    email = email.strip().lower()
    if limited(f"login:{email}", 6, 15) or limited(f"loginip:{client_ip(request)}", 30, 15):
        return login_form(next, "Too many tries. Wait 15 minutes.")
    u = DB.one("SELECT id, pw_hash, active FROM users WHERE email = %s", (email,))
    if not u or not u["active"] or not security.check_password(password, u["pw_hash"]):
        audit(email, "login_failed", client_ip(request))
        return login_form(next, "Wrong email or password.")
    t = security.token()
    DB.run("INSERT INTO sessions (token, user_id, expires) VALUES (%s, %s, %s)", (t, u["id"], now() + timedelta(hours=S.session_hours)))
    audit(email, "login", client_ip(request))
    r = RedirectResponse(next if next.startswith("/app") else "/app", 303)
    r.set_cookie(COOKIE, t, httponly=True, secure=S.secure_cookies, samesite="lax", max_age=S.session_hours * 3600, path="/")
    return r


@app.post("/app/logout")
def logout(request: Request, csrf: str = Form("")):
    user, t = current_user(request)
    if t and check_csrf(t, csrf):
        DB.run("DELETE FROM sessions WHERE token = %s", (t,))
    r = RedirectResponse("/app/login", 303)
    r.delete_cookie(COOKIE, path="/")
    return r


@app.get("/app")
def home(request: Request):
    user, t, deny = need(request)
    if deny:
        return deny
    csrf = security.csrf_for(S.secret_key, t)
    parts = []
    if user["role"] in STAFF:
        n = DB.one("SELECT COUNT(*) AS n FROM submissions WHERE status = %s", ("new",))["n"]
        parts.append(f'<div class="card"><b>{n}</b> new form submission(s). <a href="/app/inbox">Open inbox</a></div>')
    if user["role"] == "admin" and S.launcher:
        groups = {}
        for x in S.launcher:
            groups.setdefault(x.get("group", "Links"), []).append(x)
        for g, xs in groups.items():
            parts.append(f'<h2>{esc(g)}</h2><div class="grid">' + "".join(
                f'<a href="{esc(x["url"])}" target="_blank" rel="noopener"><b>{esc(x["title"])}</b><div class="muted">{esc(x.get("note", ""))}</div></a>' for x in xs) + "</div>")
    if user["role"] not in STAFF:
        mine = DB.all("SELECT form, status, created FROM submissions WHERE email = %s ORDER BY id DESC LIMIT 50", (user["email"],))
        rows = "".join(f'<tr><td>{esc(m["form"])}</td><td><span class="pill">{esc(m["status"])}</span></td><td>{esc(str(m["created"])[:16])}</td></tr>' for m in mine)
        parts.append('<div class="card"><h2>Your requests</h2>' + (f"<table>{rows}</table>" if rows else '<p class="muted">Nothing yet.</p>') + "</div>")
    forms = "".join(f'<li><a href="/app/forms/{esc(k)}">{esc(v["title"])}</a></li>' for k, v in S.forms.items())
    parts.append(f'<div class="card"><h2>Forms</h2><ul>{forms}</ul></div>')
    return page(f"Welcome, {user['name'] or user['email']}", "".join(parts), user, csrf)


@app.get("/app/forms/{name}")
def form_page(name: str, request: Request, sent: int = 0):
    f = S.forms.get(name)
    if not f:
        return page("Not found", "<p>No such form.</p>")
    user, t = current_user(request)
    fields = "".join(
        f'<label>{esc(label)}{" *" if req else ""}</label>' +
        (f'<textarea name="{esc(k)}" rows="5"{" required" if req else ""}></textarea>' if k in ("message", "details", "question")
         else f'<input name="{esc(k)}"{" type=email" if k == "email" else ""}{" required" if req else ""} value="{esc(user["email"]) if (user and k == "email") else ""}">')
        for k, label, req in f["fields"])
    ok = '<p class="ok">Thanks! We got it and will reply soon.</p>' if sent else ""
    return page(f["title"], f'{ok}<form method="post" class="card">{fields}<input name="website" style="display:none" tabindex="-1" autocomplete="off"><button>Send</button></form>',
                user, security.csrf_for(S.secret_key, t) if t else "")


@app.post("/app/forms/{name}")
async def form_submit(name: str, request: Request):
    f = S.forms.get(name)
    if not f:
        return page("Not found", "<p>No such form.</p>")
    data = await request.form()
    if data.get("website"):
        return RedirectResponse(f"/app/forms/{name}?sent=1", 303)
    if limited(f"form:{client_ip(request)}", 10, 60):
        return page(f["title"], '<p class="err">Too many messages from your connection. Try again later.</p>')
    out = {}
    for k, label, req in f["fields"]:
        v = str(data.get(k, "")).strip()[:4000]
        if req and not v:
            return page(f["title"], f'<p class="err">Please fill in: {esc(label)}.</p><p><a href="/app/forms/{esc(name)}">Back</a></p>')
        out[k] = v
    DB.run("INSERT INTO submissions (form, data, email, ip) VALUES (%s, %s, %s, %s)",
           (name, json.dumps(out), out.get("email", "").lower(), client_ip(request)))
    return RedirectResponse(f"/app/forms/{name}?sent=1", 303)


@app.get("/app/inbox")
def inbox(request: Request, status: str = ""):
    user, t, deny = need(request, STAFF)
    if deny:
        return deny
    csrf = security.csrf_for(S.secret_key, t)
    q = "SELECT * FROM submissions" + (" WHERE status = %s" if status else "") + " ORDER BY id DESC LIMIT 200"
    rows = DB.all(q, (status,) if status else ())
    opts = ["new", "in_progress", "done", "spam"]
    html_rows = ""
    for r in rows:
        d = json.loads(r["data"])
        details = "<br>".join(f"<b>{esc(k)}:</b> {esc(v)}" for k, v in d.items())
        sel = "".join(f'<option{" selected" if o == r["status"] else ""}>{o}</option>' for o in opts)
        html_rows += f"""<tr><td>#{r["id"]}<br><span class="pill">{esc(r["form"])}</span><div class="muted">{esc(str(r["created"])[:16])}</div></td><td>{details}{f'<div class="muted">Note: {esc(r["note"])}</div>' if r["note"] else ""}</td>
<td><form method="post" action="/app/inbox/{r["id"]}"><input type="hidden" name="csrf" value="{csrf}"><select name="status">{sel}</select><input name="note" placeholder="note" value="{esc(r["note"])}"><button>Save</button></form></td></tr>"""
    filt = " · ".join(f'<a href="/app/inbox?status={o}">{o}</a>' for o in [""] + opts).replace('status=">', 'status=">all')
    return page("Inbox", f'<p class="muted">Filter: {filt}</p><div class="card"><table>{html_rows or "<tr><td>No submissions.</td></tr>"}</table></div>', user, csrf)


@app.post("/app/inbox/{sid}")
def inbox_update(sid: int, request: Request, status: str = Form(...), note: str = Form(""), csrf: str = Form("")):
    user, t, deny = need(request, STAFF)
    if deny:
        return deny
    if not check_csrf(t, csrf) or status not in ("new", "in_progress", "done", "spam"):
        return page("Error", '<p class="err">That request expired. Go back and try again.</p>', user, security.csrf_for(S.secret_key, t))
    DB.run("UPDATE submissions SET status = %s, note = %s WHERE id = %s", (status, note[:500], sid))
    audit(user["email"], "submission_status", f"#{sid} -> {status}")
    return RedirectResponse("/app/inbox", 303)


@app.get("/app/users")
def users(request: Request, link: str = ""):
    user, t, deny = need(request, {"admin"})
    if deny:
        return deny
    csrf = security.csrf_for(S.secret_key, t)
    us = DB.all("SELECT id, email, name, role, active, created FROM users ORDER BY id")
    rows = "".join(f"""<tr><td>{esc(u["name"] or "")}<div class="muted">{esc(u["email"])}</div></td><td><span class="pill">{esc(u["role"])}</span></td><td>{"active" if u["active"] else "disabled"}</td>
<td>{"" if u["id"] == user["id"] else f'<form method="post" action="/app/users/{u["id"]}/toggle"><input type="hidden" name="csrf" value="{csrf}"><button>{"Disable" if u["active"] else "Enable"}</button></form>'}</td></tr>""" for u in us)
    roles = "".join(f"<option>{esc(r)}</option>" for r in S.roles)
    shown = f'<div class="card ok">Invite link (one use, 7 days):<br><b>{esc(link)}</b></div>' if link else ""
    return page("Users", f"""{shown}<div class="card"><table>{rows}</table></div>
<form method="post" action="/app/users/invite" class="card"><h2>Invite someone</h2><input type="hidden" name="csrf" value="{csrf}">
<label>Role</label><select name="role">{roles}</select><label>Note (who it's for)</label><input name="note" maxlength="80"><button>Create invite link</button></form>""", user, csrf)


@app.post("/app/users/invite")
def invite(request: Request, role: str = Form(...), note: str = Form(""), csrf: str = Form("")):
    user, t, deny = need(request, {"admin"})
    if deny:
        return deny
    if not check_csrf(t, csrf) or role not in S.roles:
        return page("Error", '<p class="err">Invalid request.</p>', user, security.csrf_for(S.secret_key, t))
    tok = security.token(24)
    DB.run("INSERT INTO invites (token, role, note, created_by, expires) VALUES (%s, %s, %s, %s, %s)", (tok, role, note[:80], user["id"], now() + timedelta(days=7)))
    audit(user["email"], "invite", f"{role} {note}")
    link = str(request.base_url).rstrip("/") + f"/app/register?t={tok}"
    return RedirectResponse("/app/users?link=" + link, 303)


@app.post("/app/users/{uid}/toggle")
def toggle(uid: int, request: Request, csrf: str = Form("")):
    user, t, deny = need(request, {"admin"})
    if deny:
        return deny
    if check_csrf(t, csrf) and uid != user["id"]:
        DB.run("UPDATE users SET active = NOT active WHERE id = %s", (uid,))
        DB.run("DELETE FROM sessions WHERE user_id = %s", (uid,))
        audit(user["email"], "user_toggle", str(uid))
    return RedirectResponse("/app/users", 303)


@app.get("/app/register")
def register_form(t: str = "", err: str = ""):
    inv = DB.one("SELECT role, expires FROM invites WHERE token = %s", (t,))
    if not inv or inv["expires"] < now():
        return page("Invite expired", "<p>This invite link has expired or was already used. Ask an admin for a new one.</p>")
    msg = f'<p class="err">{esc(err)}</p>' if err else ""
    return page("Create your login", f"""{msg}<p class="muted">You're joining {esc(S.site_name)} as <b>{esc(inv["role"])}</b>.</p>
<form method="post" class="card"><input type="hidden" name="t" value="{esc(t)}"><label>Your name</label><input name="name" maxlength="60">
<label>Email</label><input name="email" type="email" required><label>Password (10+ characters)</label><input name="password" type="password" autocomplete="new-password" required><button>Create login</button></form>""")


@app.post("/app/register")
def register(t: str = Form(...), name: str = Form(""), email: str = Form(...), password: str = Form(...)):
    inv = DB.one("SELECT role, expires FROM invites WHERE token = %s", (t,))
    if not inv or inv["expires"] < now():
        return register_form(t)
    email = email.strip().lower()
    if len(password) < 10:
        return register_form(t, "Use at least 10 characters.")
    if DB.one("SELECT id FROM users WHERE email = %s", (email,)):
        return register_form(t, "That email already has a login.")
    DB.run("INSERT INTO users (email, name, role, pw_hash) VALUES (%s, %s, %s, %s)", (email, name.strip()[:60], inv["role"], security.hash_password(password)))
    DB.run("DELETE FROM invites WHERE token = %s", (t,))
    audit(email, "register", inv["role"])
    return RedirectResponse("/app/login", 303)


@app.get("/app/account")
def account(request: Request, ok: int = 0, err: str = ""):
    user, t, deny = need(request)
    if deny:
        return deny
    csrf = security.csrf_for(S.secret_key, t)
    msg = '<p class="ok">Password changed.</p>' if ok else (f'<p class="err">{esc(err)}</p>' if err else "")
    return page("My account", f"""{msg}<form method="post" class="card"><input type="hidden" name="csrf" value="{csrf}">
<label>Current password</label><input name="current" type="password" required><label>New password (10+ characters)</label><input name="new" type="password" autocomplete="new-password" required><button>Change password</button></form>""", user, csrf)


@app.post("/app/account")
def account_save(request: Request, current: str = Form(...), new: str = Form(...), csrf: str = Form("")):
    user, t, deny = need(request)
    if deny:
        return deny
    u = DB.one("SELECT pw_hash FROM users WHERE id = %s", (user["id"],))
    if not check_csrf(t, csrf) or not security.check_password(current, u["pw_hash"]):
        return RedirectResponse("/app/account?err=Current+password+is+wrong", 303)
    if len(new) < 10:
        return RedirectResponse("/app/account?err=Use+at+least+10+characters", 303)
    DB.run("UPDATE users SET pw_hash = %s WHERE id = %s", (security.hash_password(new), user["id"]))
    DB.run("DELETE FROM sessions WHERE user_id = %s AND token <> %s", (user["id"], t))
    audit(user["email"], "password_change")
    return RedirectResponse("/app/account?ok=1", 303)


@app.get("/app/api/stats")
def stats(request: Request):
    user, t, deny = need(request, STAFF)
    if deny:
        return JSONResponse({"error": "login required"}, 401)
    return {"site": S.site_name, "users": DB.one("SELECT COUNT(*) AS n FROM users")["n"],
            "submissions": DB.all("SELECT status, COUNT(*) AS n FROM submissions GROUP BY status")}


# The real site (files synced from its GitHub repo by the git-sync sidecar) is served at /.
if os.path.isdir(S.site_root):
    app.mount("/", StaticFiles(directory=S.site_root, html=True, follow_symlink=True), name="site")
else:
    @app.get("/")
    def no_site():
        return page(S.site_name, f'<p class="muted">Site files are still syncing into {esc(S.site_root)}. <a href="/app">Log in</a></p>')
