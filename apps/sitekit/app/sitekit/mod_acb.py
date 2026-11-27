"""ACB Landscaping operations: clients & properties, lead pipeline, service catalog, quotes with online
approval, recurring jobs and a weekly schedule, crew job sheets with clock in/out and photos, invoices,
client reminders and review requests, and a dashboard. Crew never see prices or billing."""
import base64, csv, io, json, re
from datetime import date, datetime, timedelta
from urllib.parse import quote as urlq
from zoneinfo import ZoneInfo
from fastapi import Request, UploadFile
from fastapi.responses import RedirectResponse, Response

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS acb_clients (id SERIAL PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'lead', source TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS acb_properties (id SERIAL PRIMARY KEY, client_id INTEGER NOT NULL, address TEXT NOT NULL,
        area TEXT NOT NULL DEFAULT '', lot_size TEXT NOT NULL DEFAULT '', gate_code TEXT NOT NULL DEFAULT '', pets TEXT NOT NULL DEFAULT '',
        instructions TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS acb_services (id SERIAL PRIMARY KEY, name TEXT NOT NULL, unit TEXT NOT NULL DEFAULT 'visit',
        price_cents INTEGER NOT NULL DEFAULT 0, active BOOLEAN NOT NULL DEFAULT TRUE)""",
    """CREATE TABLE IF NOT EXISTS acb_quotes (id SERIAL PRIMARY KEY, client_id INTEGER NOT NULL, property_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'draft', token TEXT NOT NULL, recurrence TEXT NOT NULL DEFAULT 'none', notes TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL, approved_name TEXT NOT NULL DEFAULT '', approved_at TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS acb_quote_lines (id SERIAL PRIMARY KEY, quote_id INTEGER NOT NULL, description TEXT NOT NULL,
        qty REAL NOT NULL DEFAULT 1, price_cents INTEGER NOT NULL DEFAULT 0)""",
    """CREATE TABLE IF NOT EXISTS acb_jobs (id SERIAL PRIMARY KEY, property_id INTEGER NOT NULL, quote_id INTEGER, title TEXT NOT NULL,
        day TEXT NOT NULL DEFAULT '', crew_id INTEGER, status TEXT NOT NULL DEFAULT 'scheduled', recurrence TEXT NOT NULL DEFAULT 'none',
        est_hours REAL NOT NULL DEFAULT 0, price_cents INTEGER NOT NULL DEFAULT 0, notes TEXT NOT NULL DEFAULT '',
        completed_at TEXT NOT NULL DEFAULT '', invoice_id INTEGER)""",
    """CREATE TABLE IF NOT EXISTS acb_time (id SERIAL PRIMARY KEY, job_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
        clock_in TEXT NOT NULL, clock_out TEXT NOT NULL DEFAULT '', geo_in TEXT NOT NULL DEFAULT '', geo_out TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS acb_photos (id SERIAL PRIMARY KEY, job_id INTEGER NOT NULL, kind TEXT NOT NULL, mime TEXT NOT NULL,
        data TEXT NOT NULL, user_id INTEGER, created TEXT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS acb_invoices (id SERIAL PRIMARY KEY, client_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
        token TEXT NOT NULL, due TEXT NOT NULL, created TEXT NOT NULL, paid_at TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS acb_invoice_lines (id SERIAL PRIMARY KEY, invoice_id INTEGER NOT NULL, job_id INTEGER,
        description TEXT NOT NULL, qty REAL NOT NULL DEFAULT 1, price_cents INTEGER NOT NULL DEFAULT 0)""",
]
CLIENT_STATUS = ["lead", "quoted", "active", "past"]
JOB_STATUS = ["scheduled", "in_progress", "done", "skipped", "cancelled"]
RECUR = {"none": 0, "weekly": 7, "biweekly": 14, "monthly": 28}
DEFAULT_SERVICES = [("Weekly lawn mowing", "visit", 4500), ("Spring cleanup", "job", 22500), ("Fall cleanup", "job", 25000),
                    ("Mulch installation", "cubic yard", 9500), ("Hedge trimming", "hour", 6000),
                    ("Snow removal — driveway (seasonal)", "season", 65000), ("Snow removal — per visit", "visit", 5500),
                    ("Salting / ice control", "visit", 3500)]


def register(c):
    S, DB, esc, page, need = c.S, c.DB, c.esc, c.page, c.need
    cfg = {"tax_rate": 0.13, "tax_name": "HST", "company": S.site_name, "phone": "", "review_url": "",
           "timezone": "America/Toronto", "pay_days": 14, **S.module_config.get("acb", {})}
    TZ = ZoneInfo(cfg["timezone"])
    OFFICE = set(S.staff_roles)
    FIELD = OFFICE | {"crew"}
    DB.migrate(SCHEMA)
    if not DB.one("SELECT id FROM acb_services LIMIT 1"):
        for n, u, p in DEFAULT_SERVICES:
            DB.run("INSERT INTO acb_services (name, unit, price_cents) VALUES (%s, %s, %s)", (n, u, p))
    c.NAV.extend([("Dashboard", "/acb", OFFICE), ("Clients", "/acb/clients", OFFICE), ("Schedule", "/acb/schedule", OFFICE),
                  ("Invoices", "/acb/invoices", OFFICE), ("Messages", "/acb/messages", OFFICE), ("Services", "/acb/services", OFFICE),
                  ("My jobs", "/acb/crew", {"crew"} | OFFICE), ("My services", "/acb/my", {"client"})])
    app = c.app

    def today():
        return datetime.now(TZ).date()

    def stamp():
        return datetime.now(TZ).strftime("%Y-%m-%d %H:%M")

    def money(cents):
        return f"${(cents or 0) / 100:,.2f}"

    def cents(v):
        try:
            return int(round(float(str(v).replace("$", "").replace(",", "") or 0) * 100))
        except ValueError:
            return 0

    def tok():
        from sitekit.security import token
        return token(18)

    def ins(q, args):
        return DB.one(q + " RETURNING id", args)["id"]

    def area_of(address):
        m = re.search(r"\b([A-Z]\d[A-Z])\s?\d[A-Z]\d\b", address.upper())
        return m.group(1) if m else ""

    def maps(addresses):
        stops = [urlq(a) for a in addresses if a][:10]
        return "https://www.google.com/maps/dir/" + "/".join(stops) if stops else ""

    async def form(request):
        return {k: str(v).strip() for k, v in (await request.form()).items() if not hasattr(v, "filename")}

    def guard(request, roles):
        user, t, deny = need(request, roles)
        return user, t, deny, c.csrf_for(t)

    def bad(user, csrf):
        return page("Expired", '<p class="err">That form expired. Go back and try again.</p>', user, csrf)

    def hidden(csrf):
        return f'<input type="hidden" name="csrf" value="{csrf}">'

    def opts(values, current):
        return "".join(f'<option{" selected" if v == current else ""}>{esc(v)}</option>' for v in values)

    def quote_total(qid):
        lines = DB.all("SELECT qty, price_cents FROM acb_quote_lines WHERE quote_id = %s", (qid,))
        return int(round(sum(l["qty"] * l["price_cents"] for l in lines)))

    def invoice_totals(iid):
        sub = int(round(sum(l["qty"] * l["price_cents"] for l in DB.all("SELECT qty, price_cents FROM acb_invoice_lines WHERE invoice_id = %s", (iid,)))))
        tax = int(round(sub * cfg["tax_rate"]))
        return sub, tax, sub + tax

    def crews():
        return DB.all("SELECT id, name, email FROM users WHERE role IN ('crew', 'staff', 'admin') AND active = %s ORDER BY name", (True,))

    # ---------- dashboard
    @app.get("/acb")
    def dash(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        d0 = today(); wk = d0 - timedelta(days=d0.weekday()); we = wk + timedelta(days=6)
        n = lambda q, a=(): DB.one(q, a)["n"]
        leads = n("SELECT COUNT(*) AS n FROM acb_clients WHERE status = 'lead'")
        active = n("SELECT COUNT(*) AS n FROM acb_clients WHERE status = 'active'")
        recurring = n("SELECT COUNT(*) AS n FROM acb_jobs WHERE recurrence <> 'none' AND status IN ('scheduled', 'in_progress')")
        week = n("SELECT COUNT(*) AS n FROM acb_jobs WHERE day >= %s AND day <= %s AND status <> 'cancelled'", (wk.isoformat(), we.isoformat()))
        tday = n("SELECT COUNT(*) AS n FROM acb_jobs WHERE day = %s AND status <> 'cancelled'", (d0.isoformat(),))
        unsched = n("SELECT COUNT(*) AS n FROM acb_jobs WHERE day = '' AND status = 'scheduled'")
        decided = DB.one("SELECT SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS a, COUNT(*) AS n FROM acb_quotes WHERE status IN ('approved', 'declined', 'sent')")
        conv = f"{100 * (decided['a'] or 0) / decided['n']:.0f}%" if decided["n"] else "—"
        unpaid = overdue = 0
        for inv in DB.all("SELECT id, due FROM acb_invoices WHERE status = 'sent'"):
            tot = invoice_totals(inv["id"])[2]; unpaid += tot
            if inv["due"] < d0.isoformat():
                overdue += tot
        monthly = sum(quote_total(q["id"]) * {"weekly": 4.33, "biweekly": 2.17, "monthly": 1}.get(q["recurrence"], 0)
                      for q in DB.all("SELECT id, recurrence FROM acb_quotes WHERE status = 'approved' AND recurrence <> 'none'"))
        hrs = DB.all("SELECT j.id, j.est_hours FROM acb_jobs j WHERE j.status = 'done' AND j.completed_at >= %s", ((d0 - timedelta(days=30)).isoformat(),))
        est = sum(h["est_hours"] for h in hrs); act = 0.0
        for h in hrs:
            for te in DB.all("SELECT clock_in, clock_out FROM acb_time WHERE job_id = %s AND clock_out <> ''", (h["id"],)):
                act += (datetime.fromisoformat(te["clock_out"]) - datetime.fromisoformat(te["clock_in"])).total_seconds() / 3600
        new_req = n("SELECT COUNT(*) AS n FROM submissions WHERE status = 'new'")
        tiles = [("Recurring revenue / month", money(monthly)), ("Unpaid invoices", money(unpaid)), ("Overdue", money(overdue)),
                 ("Quote conversion", conv), ("Jobs today", tday), ("Jobs this week", week), ("Waiting to schedule", unsched),
                 ("Recurring jobs", recurring), ("Active clients", active), ("Open leads", leads),
                 ("Hours: estimated vs actual (30 days)", f"{est:.1f} vs {act:.1f}"), ("New website requests", new_req)]
        grid = "".join(f'<div class="card"><div class="muted">{esc(k)}</div><div style="font-size:1.5rem;font-weight:700">{esc(str(v))}</div></div>' for k, v in tiles)
        return page("ACB dashboard", f'<div class="grid">{grid}</div><p><a href="/acb/clients?import=1">Import website quote requests</a> · <a href="/acb/schedule">This week</a> · <a href="/acb/messages">Reminders to send</a></p>', user, csrf)

    # ---------- clients, properties, lead pipeline
    @app.get("/acb/clients")
    def clients(request: Request, status: str = "", q: str = "", imported: int = -1):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        sql = "SELECT * FROM acb_clients WHERE 1 = 1"; a = []
        if status:
            sql += " AND status = %s"; a.append(status)
        if q:
            sql += " AND (LOWER(name) LIKE %s OR LOWER(email) LIKE %s OR phone LIKE %s)"; a += [f"%{q.lower()}%"] * 2 + [f"%{q}%"]
        rows = DB.all(sql + " ORDER BY id DESC LIMIT 300", tuple(a))
        counts = {s: DB.one("SELECT COUNT(*) AS n FROM acb_clients WHERE status = %s", (s,))["n"] for s in CLIENT_STATUS}
        pipe = " → ".join(f'<a href="/acb/clients?status={s}">{s} ({counts[s]})</a>' for s in CLIENT_STATUS)
        tr = "".join(f'<tr><td><a href="/acb/clients/{r["id"]}">{esc(r["name"])}</a></td><td>{esc(r["phone"])}<div class="muted">{esc(r["email"])}</div></td><td><span class="pill">{esc(r["status"])}</span></td><td>{esc(r["source"])}</td></tr>' for r in rows)
        note = f'<p class="ok">Imported {imported} website request(s) as leads.</p>' if imported >= 0 else ""
        return page("Clients", f"""{note}<p>Pipeline: <a href="/acb/clients">all</a> · {pipe}</p>
<form class="card" method="post" action="/acb/clients/import">{hidden(csrf)}<b>Website quote requests</b> → leads <button>Import new requests</button></form>
<form method="get" class="card"><input name="q" value="{esc(q)}" placeholder="Search name, email or phone"></form>
<div class="card"><table><tr><th>Client</th><th>Contact</th><th>Status</th><th>Source</th></tr>{tr or '<tr><td>No clients yet.</td></tr>'}</table></div>
<form method="post" action="/acb/clients" class="card"><h2>Add client</h2>{hidden(csrf)}
<label>Name</label><input name="name" required><label>Phone</label><input name="phone"><label>Email</label><input name="email" type="email">
<label>Service address</label><input name="address"><label>Source</label><input name="source" placeholder="phone, referral, Facebook…"><button>Add</button></form>""", user, csrf)

    @app.post("/acb/clients")
    async def client_add(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")) or not f.get("name"):
            return bad(user, csrf)
        cid = ins("INSERT INTO acb_clients (name, phone, email, source, created) VALUES (%s, %s, %s, %s, %s)",
                  (f["name"][:120], f.get("phone", "")[:40], f.get("email", "").lower()[:120], f.get("source", "")[:60], stamp()))
        if f.get("address"):
            DB.run("INSERT INTO acb_properties (client_id, address, area) VALUES (%s, %s, %s)", (cid, f["address"][:200], area_of(f["address"])))
        c.audit(user["email"], "acb_client_add", str(cid))
        return RedirectResponse(f"/acb/clients/{cid}", 303)

    @app.post("/acb/clients/import")
    async def client_import(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")):
            return bad(user, csrf)
        n = 0
        for s in DB.all("SELECT id, data FROM submissions WHERE form = 'quote' AND status = 'new' ORDER BY id"):
            d = json.loads(s["data"])
            cid = ins("INSERT INTO acb_clients (name, phone, email, source, notes, created) VALUES (%s, %s, %s, %s, %s, %s)",
                      (d.get("name", "Website lead")[:120], d.get("phone", "")[:40], d.get("email", "").lower()[:120], "website",
                       f"{d.get('service', '')}: {d.get('details', '')}"[:1000], stamp()))
            if d.get("address"):
                DB.run("INSERT INTO acb_properties (client_id, address, area) VALUES (%s, %s, %s)", (cid, d["address"][:200], area_of(d["address"])))
            DB.run("UPDATE submissions SET status = 'done', note = %s WHERE id = %s", (f"imported as client #{cid}", s["id"]))
            n += 1
        c.audit(user["email"], "acb_import", str(n))
        return RedirectResponse(f"/acb/clients?imported={n}", 303)

    @app.get("/acb/clients/{cid}")
    def client_view(cid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        cl = DB.one("SELECT * FROM acb_clients WHERE id = %s", (cid,))
        if not cl:
            return page("Not found", "<p>No such client.</p>", user, csrf)
        props = DB.all("SELECT * FROM acb_properties WHERE client_id = %s ORDER BY id", (cid,))
        quotes = DB.all("SELECT * FROM acb_quotes WHERE client_id = %s ORDER BY id DESC", (cid,))
        jobs = DB.all("SELECT j.* FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id WHERE p.client_id = %s ORDER BY j.id DESC LIMIT 50", (cid,))
        invs = DB.all("SELECT * FROM acb_invoices WHERE client_id = %s ORDER BY id DESC", (cid,))
        ptr = "".join(f"""<tr><td>{esc(p['address'])}<div class="muted">area {esc(p['area'] or '—')} · lot {esc(p['lot_size'] or '—')}</div></td>
<td>Gate: {esc(p['gate_code'] or '—')}<br>Pets: {esc(p['pets'] or '—')}</td><td>{esc(p['instructions'])}</td>
<td><a href="/acb/quotes/new?property={p['id']}">New quote</a> · <a href="/acb/jobs/new?property={p['id']}">New job</a></td></tr>""" for p in props)
        qtr = "".join(f'<tr><td><a href="/acb/quotes/{q["id"]}">Quote #{q["id"]}</a></td><td><span class="pill">{esc(q["status"])}</span></td><td>{money(quote_total(q["id"]))}</td><td>{esc(q["recurrence"])}</td></tr>' for q in quotes)
        jtr = "".join(f'<tr><td><a href="/acb/jobs/{j["id"]}">{esc(j["title"])}</a></td><td>{esc(j["day"] or "to schedule")}</td><td><span class="pill">{esc(j["status"])}</span></td></tr>' for j in jobs)
        itr = "".join(f'<tr><td><a href="/acb/invoices/{i["id"]}">Invoice #{i["id"]}</a></td><td><span class="pill">{esc(i["status"])}</span></td><td>{money(invoice_totals(i["id"])[2])}</td><td>due {esc(i["due"])}</td></tr>' for i in invs)
        return page(cl["name"], f"""<form method="post" action="/acb/clients/{cid}" class="card">{hidden(csrf)}
<label>Status</label><select name="status">{opts(CLIENT_STATUS, cl['status'])}</select><label>Phone</label><input name="phone" value="{esc(cl['phone'])}">
<label>Email</label><input name="email" value="{esc(cl['email'])}"><label>Notes</label><textarea name="notes" rows="3">{esc(cl['notes'])}</textarea><button>Save</button></form>
<div class="card"><h2>Properties</h2><table>{ptr or '<tr><td>No property yet.</td></tr>'}</table>
<form method="post" action="/acb/clients/{cid}/property">{hidden(csrf)}<label>Address (with postal code)</label><input name="address" required>
<label>Lot size</label><input name="lot_size" placeholder="e.g. 5,000 sq ft"><label>Gate code</label><input name="gate_code"><label>Pets</label><input name="pets">
<label>Site instructions</label><textarea name="instructions" rows="2"></textarea><button>Add property</button></form></div>
<div class="card"><h2>Quotes</h2><table>{qtr or '<tr><td>None.</td></tr>'}</table></div>
<div class="card"><h2>Jobs</h2><table>{jtr or '<tr><td>None.</td></tr>'}</table></div>
<div class="card"><h2>Invoices</h2><table>{itr or '<tr><td>None.</td></tr>'}</table>
<form method="post" action="/acb/invoices/from-jobs">{hidden(csrf)}<input type="hidden" name="client_id" value="{cid}"><button>Invoice all completed, unbilled jobs</button></form></div>""", user, csrf)

    @app.post("/acb/clients/{cid}")
    async def client_save(cid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")) or f.get("status") not in CLIENT_STATUS:
            return bad(user, csrf)
        DB.run("UPDATE acb_clients SET status = %s, phone = %s, email = %s, notes = %s WHERE id = %s",
               (f["status"], f.get("phone", "")[:40], f.get("email", "").lower()[:120], f.get("notes", "")[:2000], cid))
        return RedirectResponse(f"/acb/clients/{cid}", 303)

    @app.post("/acb/clients/{cid}/property")
    async def property_add(cid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")) or not f.get("address"):
            return bad(user, csrf)
        DB.run("INSERT INTO acb_properties (client_id, address, area, lot_size, gate_code, pets, instructions) VALUES (%s, %s, %s, %s, %s, %s, %s)",
               (cid, f["address"][:200], area_of(f["address"]), f.get("lot_size", "")[:60], f.get("gate_code", "")[:40], f.get("pets", "")[:80], f.get("instructions", "")[:1000]))
        return RedirectResponse(f"/acb/clients/{cid}", 303)

    # ---------- service catalog
    @app.get("/acb/services")
    def services(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        rows = DB.all("SELECT * FROM acb_services ORDER BY active DESC, name")
        tr = "".join(f"""<tr><td>{esc(s['name'])}</td><td>{esc(s['unit'])}</td><td><form method="post" action="/acb/services/{s['id']}" class="inline">{hidden(csrf)}
<input name="price" value="{s['price_cents'] / 100:.2f}" style="width:7rem"> <select name="active"><option value="1"{' selected' if s['active'] else ''}>active</option><option value="0"{'' if s['active'] else ' selected'}>hidden</option></select> <button>Save</button></form></td></tr>""" for s in rows)
        return page("Service catalog", f"""<div class="card"><table><tr><th>Service</th><th>Unit</th><th>Price (before {esc(cfg['tax_name'])})</th></tr>{tr}</table></div>
<form method="post" action="/acb/services" class="card"><h2>Add service</h2>{hidden(csrf)}<label>Name</label><input name="name" required>
<label>Unit</label><input name="unit" value="visit"><label>Price</label><input name="price" required><button>Add</button></form>""", user, csrf)

    @app.post("/acb/services")
    async def service_add(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")) or not f.get("name"):
            return bad(user, csrf)
        DB.run("INSERT INTO acb_services (name, unit, price_cents) VALUES (%s, %s, %s)", (f["name"][:120], f.get("unit", "visit")[:30], cents(f.get("price"))))
        return RedirectResponse("/acb/services", 303)

    @app.post("/acb/services/{sid}")
    async def service_save(sid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")):
            return bad(user, csrf)
        DB.run("UPDATE acb_services SET price_cents = %s, active = %s WHERE id = %s", (cents(f.get("price")), f.get("active") == "1", sid))
        return RedirectResponse("/acb/services", 303)

    # ---------- quotes + online approval
    @app.get("/acb/quotes/new")
    def quote_new(request: Request, property: int):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        p = DB.one("SELECT p.*, c.name FROM acb_properties p JOIN acb_clients c ON c.id = p.client_id WHERE p.id = %s", (property,))
        if not p:
            return page("Not found", "<p>No such property.</p>", user, csrf)
        svc = DB.all("SELECT * FROM acb_services WHERE active = %s ORDER BY name", (True,))
        so = '<option value="">—</option>' + "".join(f'<option value="{s["id"]}">{esc(s["name"])} ({money(s["price_cents"])}/{esc(s["unit"])})</option>' for s in svc)
        rows = "".join(f'<tr><td><select name="svc{i}">{so}</select></td><td><input name="qty{i}" value="1" style="width:5rem"></td><td><input name="price{i}" placeholder="catalog price" style="width:8rem"></td></tr>' for i in range(6))
        return page(f"New quote · {p['name']}", f"""<p class="muted">{esc(p['address'])}</p><form method="post" action="/acb/quotes" class="card">{hidden(csrf)}
<input type="hidden" name="property_id" value="{p['id']}"><table><tr><th>Service</th><th>Qty</th><th>Price override</th></tr>{rows}</table>
<label>Repeats (for maintenance plans)</label><select name="recurrence">{opts(list(RECUR), 'none')}</select>
<label>Notes for the client</label><textarea name="notes" rows="3"></textarea><button>Save draft</button></form>""", user, csrf)

    @app.post("/acb/quotes")
    async def quote_create(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        p = DB.one("SELECT * FROM acb_properties WHERE id = %s", (int(f.get("property_id", 0) or 0),))
        if not c.check_csrf(t, f.get("csrf")) or not p or f.get("recurrence") not in RECUR:
            return bad(user, csrf)
        qid = ins("INSERT INTO acb_quotes (client_id, property_id, token, recurrence, notes, created) VALUES (%s, %s, %s, %s, %s, %s)",
                  (p["client_id"], p["id"], tok(), f["recurrence"], f.get("notes", "")[:2000], stamp()))
        for i in range(6):
            sid = f.get(f"svc{i}")
            if not sid:
                continue
            s = DB.one("SELECT * FROM acb_services WHERE id = %s", (int(sid),))
            if s:
                price = cents(f.get(f"price{i}")) if f.get(f"price{i}") else s["price_cents"]
                qty = float(f.get(f"qty{i}") or 1)
                DB.run("INSERT INTO acb_quote_lines (quote_id, description, qty, price_cents) VALUES (%s, %s, %s, %s)", (qid, f"{s['name']} ({s['unit']})", qty, price))
        c.audit(user["email"], "acb_quote_create", str(qid))
        return RedirectResponse(f"/acb/quotes/{qid}", 303)

    def quote_html(q, public=False):
        lines = DB.all("SELECT * FROM acb_quote_lines WHERE quote_id = %s ORDER BY id", (q["id"],))
        sub = quote_total(q["id"]); tax = int(round(sub * cfg["tax_rate"]))
        tr = "".join(f'<tr><td>{esc(l["description"])}</td><td>{l["qty"]:g}</td><td>{money(l["price_cents"])}</td><td>{money(int(round(l["qty"] * l["price_cents"])))}</td></tr>' for l in lines)
        p = DB.one("SELECT p.address, c.name FROM acb_properties p JOIN acb_clients c ON c.id = p.client_id WHERE p.id = %s", (q["property_id"],))
        rec = f'<p>Repeats: <b>{esc(q["recurrence"])}</b> (price per visit)</p>' if q["recurrence"] != "none" else ""
        return f"""<div class="card"><p><b>{esc(cfg['company'])}</b> {esc(cfg['phone'])}<br>Quote #{q['id']} for {esc(p['name'])} · {esc(p['address'])}</p>
<table><tr><th>Item</th><th>Qty</th><th>Price</th><th>Total</th></tr>{tr}
<tr><td colspan="3">Subtotal</td><td>{money(sub)}</td></tr><tr><td colspan="3">{esc(cfg['tax_name'])} {cfg['tax_rate'] * 100:g}%</td><td>{money(tax)}</td></tr>
<tr><td colspan="3"><b>Total</b></td><td><b>{money(sub + tax)}</b></td></tr></table>{rec}<p>{esc(q['notes'])}</p></div>"""

    @app.get("/acb/quotes/{qid}")
    def quote_view(qid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        q = DB.one("SELECT * FROM acb_quotes WHERE id = %s", (qid,))
        if not q:
            return page("Not found", "<p>No such quote.</p>", user, csrf)
        link = str(request.base_url).rstrip("/") + f"/q/{q['token']}"
        acts = f"""<form method="post" action="/acb/quotes/{qid}/send" class="inline">{hidden(csrf)}<button>Mark as sent</button></form>""" if q["status"] == "draft" else ""
        appr = f'<p class="ok">Approved by {esc(q["approved_name"])} on {esc(q["approved_at"])}</p>' if q["status"] == "approved" else ""
        return page(f"Quote #{qid} · {q['status']}", f"""{appr}{quote_html(q)}<div class="card"><b>Client approval link</b> (send by text or email):<br><code>{esc(link)}</code><br>{acts}
<a href="/acb/clients/{q['client_id']}">Back to client</a></div>""", user, csrf)

    @app.post("/acb/quotes/{qid}/send")
    async def quote_send(qid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")):
            return bad(user, csrf)
        q = DB.one("SELECT client_id FROM acb_quotes WHERE id = %s", (qid,))
        DB.run("UPDATE acb_quotes SET status = 'sent' WHERE id = %s AND status = 'draft'", (qid,))
        DB.run("UPDATE acb_clients SET status = 'quoted' WHERE id = %s AND status = 'lead'", (q["client_id"],))
        return RedirectResponse(f"/acb/quotes/{qid}", 303)

    @app.get("/q/{token}")
    def public_quote(token: str):
        q = DB.one("SELECT * FROM acb_quotes WHERE token = %s", (token,))
        if not q or q["status"] == "draft":
            return page("Quote", "<p>This quote link isn't active.</p>")
        if q["status"] != "sent":
            return page("Quote", f'{quote_html(q, True)}<p class="ok">This quote is {esc(q["status"])}. Thank you!</p>')
        return page("Your quote", f"""{quote_html(q, True)}<form method="post" class="card"><label>Type your full name to approve</label>
<input name="name" required maxlength="80"><label><input type="checkbox" name="agree" value="1" required style="width:auto"> I approve this quote</label>
<button name="decision" value="approve">Approve</button> <button name="decision" value="decline" formnovalidate style="background:#777">Decline</button></form>""")

    @app.post("/q/{token}")
    async def public_quote_decide(token: str, request: Request):
        if c.limited(f"quote:{c.client_ip(request)}", 20, 60):
            return page("Quote", '<p class="err">Too many tries. Try later.</p>')
        f = await form(request)
        q = DB.one("SELECT * FROM acb_quotes WHERE token = %s AND status = 'sent'", (token,))
        if not q:
            return RedirectResponse(f"/q/{token}", 303)
        if f.get("decision") == "decline":
            DB.run("UPDATE acb_quotes SET status = 'declined' WHERE id = %s", (q["id"],))
            c.audit("client", "acb_quote_declined", str(q["id"]))
            return RedirectResponse(f"/q/{token}", 303)
        if not f.get("name") or f.get("agree") != "1":
            return RedirectResponse(f"/q/{token}", 303)
        DB.run("UPDATE acb_quotes SET status = 'approved', approved_name = %s, approved_at = %s WHERE id = %s", (f["name"][:80], stamp(), q["id"]))
        DB.run("UPDATE acb_clients SET status = 'active' WHERE id = %s", (q["client_id"],))
        lines = DB.all("SELECT description FROM acb_quote_lines WHERE quote_id = %s", (q["id"],))
        title = ", ".join(l["description"].split(" (")[0] for l in lines)[:120] or f"Quote #{q['id']}"
        DB.run("INSERT INTO acb_jobs (property_id, quote_id, title, recurrence, price_cents) VALUES (%s, %s, %s, %s, %s)",
               (q["property_id"], q["id"], title, q["recurrence"], quote_total(q["id"])))
        c.audit("client", "acb_quote_approved", f"{q['id']} by {f['name'][:80]}")
        return RedirectResponse(f"/q/{token}", 303)

    # ---------- jobs, schedule, crews
    @app.get("/acb/jobs/new")
    def job_new(request: Request, property: int):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        p = DB.one("SELECT * FROM acb_properties WHERE id = %s", (property,))
        if not p:
            return page("Not found", "<p>No such property.</p>", user, csrf)
        return page("New job", f"""<p class="muted">{esc(p['address'])}</p><form method="post" action="/acb/jobs" class="card">{hidden(csrf)}
<input type="hidden" name="property_id" value="{p['id']}"><label>What</label><input name="title" required><label>Day</label><input type="date" name="day">
<label>Repeats</label><select name="recurrence">{opts(list(RECUR), 'none')}</select><label>Estimated hours</label><input name="est_hours" value="1">
<label>Price per visit</label><input name="price" value="0"><button>Create job</button></form>""", user, csrf)

    @app.post("/acb/jobs")
    async def job_create(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")) or not f.get("title") or f.get("recurrence") not in RECUR:
            return bad(user, csrf)
        jid = ins("INSERT INTO acb_jobs (property_id, title, day, recurrence, est_hours, price_cents) VALUES (%s, %s, %s, %s, %s, %s)",
                  (int(f["property_id"]), f["title"][:120], f.get("day", "")[:10], f["recurrence"], float(f.get("est_hours") or 0), cents(f.get("price"))))
        return RedirectResponse(f"/acb/jobs/{jid}", 303)

    def job_row(jid):
        return DB.one("""SELECT j.*, p.address, p.area, p.gate_code, p.pets, p.instructions, p.client_id, c.name AS client, c.phone, c.email,
            u.name AS crew FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id JOIN acb_clients c ON c.id = p.client_id
            LEFT JOIN users u ON u.id = j.crew_id WHERE j.id = %s""", (jid,))

    @app.get("/acb/jobs/{jid}")
    def job_view(jid: int, request: Request):
        user, t, deny, csrf = guard(request, FIELD)
        if deny:
            return deny
        j = job_row(jid)
        if not j or (user["role"] == "crew" and j["crew_id"] != user["id"]):
            return page("Not found", "<p>No such job on your list.</p>", user, csrf)
        office = user["role"] in OFFICE
        photos = DB.all("SELECT id, kind FROM acb_photos WHERE job_id = %s ORDER BY id", (jid,))
        ph = "".join(f'<a href="/acb/photos/{p["id"]}" target="_blank"><img src="/acb/photos/{p["id"]}" alt="{esc(p["kind"])} photo" style="height:120px;margin:4px;border-radius:8px"></a>' for p in photos)
        times = DB.all("SELECT t.*, u.name FROM acb_time t JOIN users u ON u.id = t.user_id WHERE t.job_id = %s ORDER BY t.id", (jid,))
        tt = "".join(f'<tr><td>{esc(x["name"])}</td><td>{esc(x["clock_in"])}</td><td>{esc(x["clock_out"] or "on site")}</td></tr>' for x in times)
        open_t = DB.one("SELECT id FROM acb_time WHERE job_id = %s AND user_id = %s AND clock_out = ''", (jid, user["id"]))
        clock = f"""<form method="post" action="/acb/jobs/{jid}/clock" class="inline" id="clk">{hidden(csrf)}<input type="hidden" name="geo" id="geo">
<button>{'Clock out' if open_t else 'Clock in'}</button></form>
<script>navigator.geolocation&&navigator.geolocation.getCurrentPosition(p=>{{document.getElementById('geo').value=p.coords.latitude.toFixed(5)+','+p.coords.longitude.toFixed(5)}});</script>"""
        edit = ""
        if office:
            co = '<option value="">— unassigned —</option>' + "".join(f'<option value="{u["id"]}"{" selected" if u["id"] == j["crew_id"] else ""}>{esc(u["name"] or u["email"])}</option>' for u in crews())
            edit = f"""<form method="post" action="/acb/jobs/{jid}" class="card">{hidden(csrf)}<h2>Schedule</h2><label>Day</label><input type="date" name="day" value="{esc(j['day'])}">
<label>Crew</label><select name="crew_id">{co}</select><label>Status</label><select name="status">{opts(JOB_STATUS, j['status'])}</select>
<label>Repeats</label><select name="recurrence">{opts(list(RECUR), j['recurrence'])}</select><label>Estimated hours</label><input name="est_hours" value="{j['est_hours']:g}">
<label>Price per visit</label><input name="price" value="{j['price_cents'] / 100:.2f}"><label>Notes</label><textarea name="notes" rows="2">{esc(j['notes'])}</textarea><button>Save</button></form>"""
        done = "" if j["status"] in ("done", "cancelled") else f'<form method="post" action="/acb/jobs/{jid}/done" class="inline">{hidden(csrf)}<button>Mark done</button></form>'
        return page(f"{j['title']}", f"""<div class="card"><p><b>{esc(j['client'])}</b> · {esc(j['address'])} · <a href="{maps([j['address']])}" target="_blank">Directions</a></p>
<p>Gate code: <b>{esc(j['gate_code'] or '—')}</b> · Pets: <b>{esc(j['pets'] or '—')}</b></p><p>{esc(j['instructions'])}</p>
<p>Day: <b>{esc(j['day'] or 'to schedule')}</b> · Crew: {esc(j['crew'] or 'unassigned')} · Status: <span class="pill">{esc(j['status'])}</span></p>
<p>{clock} {done}</p></div>
<div class="card"><h2>Photos (before / after)</h2>{ph or '<p class="muted">No photos yet.</p>'}
<form method="post" action="/acb/jobs/{jid}/photo" enctype="multipart/form-data">{hidden(csrf)}<select name="kind" style="width:auto"><option>before</option><option>after</option></select>
<input type="file" name="file" accept="image/*" capture="environment" required><button>Upload</button></form>
<p class="muted">Job photos only, no people in the shot.</p></div>
<div class="card"><h2>Time on site</h2><table>{tt or '<tr><td>None yet.</td></tr>'}</table></div>{edit}""", user, csrf)

    @app.post("/acb/jobs/{jid}")
    async def job_save(jid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")) or f.get("status") not in JOB_STATUS or f.get("recurrence") not in RECUR:
            return bad(user, csrf)
        DB.run("UPDATE acb_jobs SET day = %s, crew_id = %s, status = %s, recurrence = %s, est_hours = %s, price_cents = %s, notes = %s WHERE id = %s",
               (f.get("day", "")[:10], int(f["crew_id"]) if f.get("crew_id") else None, f["status"], f["recurrence"], float(f.get("est_hours") or 0),
                cents(f.get("price")), f.get("notes", "")[:1000], jid))
        return RedirectResponse(f"/acb/jobs/{jid}", 303)

    def complete(jid, who):
        j = DB.one("SELECT * FROM acb_jobs WHERE id = %s", (jid,))
        if not j or j["status"] in ("done", "cancelled"):
            return
        DB.run("UPDATE acb_jobs SET status = 'done', completed_at = %s WHERE id = %s", (stamp(), jid))
        DB.run("UPDATE acb_time SET clock_out = %s WHERE job_id = %s AND clock_out = ''", (datetime.now(TZ).strftime("%Y-%m-%dT%H:%M"), jid))
        step = RECUR.get(j["recurrence"], 0)
        if step:
            base = date.fromisoformat(j["day"]) if j["day"] else today()
            DB.run("INSERT INTO acb_jobs (property_id, quote_id, title, day, crew_id, recurrence, est_hours, price_cents) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                   (j["property_id"], j["quote_id"], j["title"], (base + timedelta(days=step)).isoformat(), j["crew_id"], j["recurrence"], j["est_hours"], j["price_cents"]))
        c.audit(who, "acb_job_done", str(jid))

    @app.post("/acb/jobs/{jid}/done")
    async def job_done(jid: int, request: Request):
        user, t, deny, csrf = guard(request, FIELD)
        if deny:
            return deny
        f = await form(request)
        j = DB.one("SELECT crew_id FROM acb_jobs WHERE id = %s", (jid,))
        if not c.check_csrf(t, f.get("csrf")) or not j or (user["role"] == "crew" and j["crew_id"] != user["id"]):
            return bad(user, csrf)
        complete(jid, user["email"])
        return RedirectResponse(f"/acb/jobs/{jid}", 303)

    @app.post("/acb/jobs/{jid}/clock")
    async def job_clock(jid: int, request: Request):
        user, t, deny, csrf = guard(request, FIELD)
        if deny:
            return deny
        f = await form(request)
        j = DB.one("SELECT crew_id, status FROM acb_jobs WHERE id = %s", (jid,))
        if not c.check_csrf(t, f.get("csrf")) or not j or (user["role"] == "crew" and j["crew_id"] != user["id"]):
            return bad(user, csrf)
        geo = f.get("geo", "")[:40]
        if not re.fullmatch(r"-?\d+\.\d+,-?\d+\.\d+|", geo):
            geo = ""
        nowt = datetime.now(TZ).strftime("%Y-%m-%dT%H:%M")
        o = DB.one("SELECT id FROM acb_time WHERE job_id = %s AND user_id = %s AND clock_out = ''", (jid, user["id"]))
        if o:
            DB.run("UPDATE acb_time SET clock_out = %s, geo_out = %s WHERE id = %s", (nowt, geo, o["id"]))
        else:
            DB.run("INSERT INTO acb_time (job_id, user_id, clock_in, geo_in) VALUES (%s, %s, %s, %s)", (jid, user["id"], nowt, geo))
            DB.run("UPDATE acb_jobs SET status = 'in_progress' WHERE id = %s AND status = 'scheduled'", (jid,))
        return RedirectResponse(f"/acb/jobs/{jid}", 303)

    @app.post("/acb/jobs/{jid}/photo")
    async def job_photo(jid: int, request: Request):
        user, t, deny, csrf = guard(request, FIELD)
        if deny:
            return deny
        data = await request.form()
        j = DB.one("SELECT crew_id FROM acb_jobs WHERE id = %s", (jid,))
        up = data.get("file")
        if not c.check_csrf(t, data.get("csrf")) or not j or (user["role"] == "crew" and j["crew_id"] != user["id"]) or not hasattr(up, "read"):
            return bad(user, csrf)
        raw = await up.read()
        mime = up.content_type or ""
        if mime not in ("image/jpeg", "image/png", "image/webp", "image/heic") or len(raw) > 6 * 1024 * 1024:
            return page("Photo", '<p class="err">Use a JPEG, PNG, WebP or HEIC photo under 6 MB.</p>', user, csrf)
        kind = "after" if data.get("kind") == "after" else "before"
        DB.run("INSERT INTO acb_photos (job_id, kind, mime, data, user_id, created) VALUES (%s, %s, %s, %s, %s, %s)",
               (jid, kind, mime, base64.b64encode(raw).decode(), user["id"], stamp()))
        return RedirectResponse(f"/acb/jobs/{jid}", 303)

    @app.get("/acb/photos/{pid}")
    def photo(pid: int, request: Request):
        user, t, deny, csrf = guard(request, FIELD)
        if deny:
            return deny
        p = DB.one("SELECT ph.mime, ph.data, j.crew_id FROM acb_photos ph JOIN acb_jobs j ON j.id = ph.job_id WHERE ph.id = %s", (pid,))
        if not p or (user["role"] == "crew" and p["crew_id"] != user["id"]):
            return Response(status_code=404)
        return Response(base64.b64decode(p["data"]), media_type=p["mime"], headers={"Cache-Control": "private, max-age=3600"})

    @app.get("/acb/schedule")
    def schedule(request: Request, week: str = ""):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        try:
            d0 = date.fromisoformat(week)
        except ValueError:
            d0 = today()
        start = d0 - timedelta(days=d0.weekday())
        out = []
        for i in range(7):
            d = start + timedelta(days=i)
            jobs = DB.all("""SELECT j.id, j.title, j.status, p.address, p.area, u.name AS crew FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id
                LEFT JOIN users u ON u.id = j.crew_id WHERE j.day = %s AND j.status <> 'cancelled' ORDER BY p.area, p.address""", (d.isoformat(),))
            rows = "".join(f'<tr><td><span class="pill">{esc(j["area"] or "—")}</span></td><td><a href="/acb/jobs/{j["id"]}">{esc(j["title"])}</a><div class="muted">{esc(j["address"])}</div></td><td>{esc(j["crew"] or "unassigned")}</td><td>{esc(j["status"])}</td></tr>' for j in jobs)
            route = maps([j["address"] for j in jobs])
            out.append(f'<div class="card"><h2>{d.strftime("%a %b %d")}{" · today" if d == today() else ""}</h2>' +
                       (f'<table>{rows}</table><p><a href="{route}" target="_blank">Route for the day (grouped by area)</a></p>' if jobs else '<p class="muted">Nothing booked.</p>') + "</div>")
        unsched = DB.all("SELECT j.id, j.title, p.address FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id WHERE j.day = '' AND j.status = 'scheduled' ORDER BY j.id")
        us = "".join(f'<li><a href="/acb/jobs/{j["id"]}">{esc(j["title"])}</a> — {esc(j["address"])}</li>' for j in unsched)
        nav = f'<p><a href="/acb/schedule?week={(start - timedelta(days=7)).isoformat()}">← Previous week</a> · <a href="/acb/schedule">This week</a> · <a href="/acb/schedule?week={(start + timedelta(days=7)).isoformat()}">Next week →</a></p>'
        rain = f"""<form method="post" action="/acb/schedule/shift" class="card">{hidden(csrf)}<b>Rain day?</b> Move every open job from
<input type="date" name="day" value="{today().isoformat()}" style="width:auto"> to the next working day. <button>Shift</button></form>"""
        return page(f"Schedule · week of {start.strftime('%b %d')}", nav + (f'<div class="card"><h2>Waiting to schedule</h2><ul>{us}</ul></div>' if us else "") + rain + "".join(out), user, csrf)

    @app.post("/acb/schedule/shift")
    async def shift(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        try:
            d = date.fromisoformat(f.get("day", ""))
        except ValueError:
            return bad(user, csrf)
        if not c.check_csrf(t, f.get("csrf")):
            return bad(user, csrf)
        nxt = d + timedelta(days=1)
        while nxt.weekday() == 6:
            nxt += timedelta(days=1)
        DB.run("UPDATE acb_jobs SET day = %s WHERE day = %s AND status = 'scheduled'", (nxt.isoformat(), d.isoformat()))
        c.audit(user["email"], "acb_rain_shift", f"{d} -> {nxt}")
        return RedirectResponse(f"/acb/schedule?week={nxt.isoformat()}", 303)

    @app.get("/acb/crew")
    def crew_home(request: Request):
        user, t, deny, csrf = guard(request, FIELD)
        if deny:
            return deny
        d0 = today()
        jobs = DB.all("""SELECT j.id, j.title, j.day, j.status, p.address, p.area FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id
            WHERE j.crew_id = %s AND j.day >= %s AND j.day <= %s AND j.status IN ('scheduled', 'in_progress') ORDER BY j.day, p.area, p.address""",
                      (user["id"], d0.isoformat(), (d0 + timedelta(days=7)).isoformat()))
        todays = [j for j in jobs if j["day"] == d0.isoformat()]
        li = "".join(f'<li><b>{esc(j["day"])}</b> · <a href="/acb/jobs/{j["id"]}">{esc(j["title"])}</a> — {esc(j["address"])} <span class="pill">{esc(j["status"])}</span></li>' for j in jobs)
        route = maps([j["address"] for j in todays])
        return page("My jobs", (f'<p><a href="{route}" target="_blank">Today\'s route ({len(todays)} stops)</a></p>' if todays else "") +
                    f'<div class="card"><ul>{li or "<li>No jobs in the next 7 days.</li>"}</ul></div>', user, csrf)

    # ---------- invoices
    @app.post("/acb/invoices/from-jobs")
    async def invoice_from_jobs(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        cid = int(f.get("client_id", 0) or 0)
        if not c.check_csrf(t, f.get("csrf")):
            return bad(user, csrf)
        jobs = DB.all("""SELECT j.* FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id
            WHERE p.client_id = %s AND j.status = 'done' AND j.invoice_id IS NULL ORDER BY j.day""", (cid,))
        if not jobs:
            return page("Nothing to bill", '<p>No completed, unbilled jobs for this client.</p><p><a href="javascript:history.back()">Back</a></p>', user, csrf)
        iid = ins("INSERT INTO acb_invoices (client_id, token, due, created) VALUES (%s, %s, %s, %s)",
                  (cid, tok(), (today() + timedelta(days=int(cfg["pay_days"]))).isoformat(), stamp()))
        for j in jobs:
            DB.run("INSERT INTO acb_invoice_lines (invoice_id, job_id, description, qty, price_cents) VALUES (%s, %s, %s, 1, %s)",
                   (iid, j["id"], f"{j['title']} — {j['day'] or j['completed_at'][:10]}", j["price_cents"]))
            DB.run("UPDATE acb_jobs SET invoice_id = %s WHERE id = %s", (iid, j["id"]))
        c.audit(user["email"], "acb_invoice_create", str(iid))
        return RedirectResponse(f"/acb/invoices/{iid}", 303)

    @app.get("/acb/invoices")
    def invoices(request: Request, status: str = ""):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        rows = DB.all("SELECT i.*, c.name FROM acb_invoices i JOIN acb_clients c ON c.id = i.client_id" + (" WHERE i.status = %s" if status else "") + " ORDER BY i.id DESC LIMIT 300", (status,) if status else ())
        d0 = today().isoformat()
        tr = "".join(f'<tr><td><a href="/acb/invoices/{i["id"]}">#{i["id"]}</a></td><td>{esc(i["name"])}</td><td><span class="pill">{"overdue" if i["status"] == "sent" and i["due"] < d0 else esc(i["status"])}</span></td><td>{money(invoice_totals(i["id"])[2])}</td><td>{esc(i["due"])}</td></tr>' for i in rows)
        f = " · ".join(f'<a href="/acb/invoices?status={s}">{s or "all"}</a>' for s in ["", "draft", "sent", "paid"])
        cl = "".join(f'<option value="{x["id"]}">{esc(x["name"])}</option>' for x in DB.all("SELECT id, name FROM acb_clients WHERE status = 'active' ORDER BY name"))
        return page("Invoices", f"""<p>{f} · <a href="/acb/invoices.csv">Export CSV (QuickBooks / Xero)</a></p>
<form method="post" action="/acb/invoices/from-jobs" class="card">{hidden(csrf)}<b>Month-end billing:</b> <select name="client_id" style="width:auto">{cl}</select> <button>Invoice completed jobs</button></form>
<div class="card"><table><tr><th>#</th><th>Client</th><th>Status</th><th>Total</th><th>Due</th></tr>{tr or '<tr><td>No invoices.</td></tr>'}</table></div>""", user, csrf)

    def invoice_html(i):
        lines = DB.all("SELECT * FROM acb_invoice_lines WHERE invoice_id = %s ORDER BY id", (i["id"],))
        sub, tax, tot = invoice_totals(i["id"])
        cl = DB.one("SELECT name, email FROM acb_clients WHERE id = %s", (i["client_id"],))
        tr = "".join(f'<tr><td>{esc(l["description"])}</td><td>{l["qty"]:g}</td><td>{money(l["price_cents"])}</td></tr>' for l in lines)
        return f"""<div class="card"><p><b>{esc(cfg['company'])}</b> {esc(cfg['phone'])}<br>Invoice #{i['id']} for {esc(cl['name'])} · due {esc(i['due'])}</p>
<table><tr><th>Item</th><th>Qty</th><th>Amount</th></tr>{tr}<tr><td colspan="2">Subtotal</td><td>{money(sub)}</td></tr>
<tr><td colspan="2">{esc(cfg['tax_name'])} {cfg['tax_rate'] * 100:g}%</td><td>{money(tax)}</td></tr><tr><td colspan="2"><b>Total</b></td><td><b>{money(tot)}</b></td></tr></table></div>"""

    @app.get("/acb/invoices.csv")
    def invoices_csv(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        buf = io.StringIO(); w = csv.writer(buf)
        w.writerow(["InvoiceNo", "Customer", "Email", "InvoiceDate", "DueDate", "Status", "Item", "Qty", "Rate", "Amount", "TaxName", "TaxAmount"])
        for i in DB.all("SELECT i.*, c.name, c.email FROM acb_invoices i JOIN acb_clients c ON c.id = i.client_id ORDER BY i.id"):
            for l in DB.all("SELECT * FROM acb_invoice_lines WHERE invoice_id = %s", (i["id"],)):
                amt = l["qty"] * l["price_cents"] / 100
                w.writerow([i["id"], i["name"], i["email"], i["created"][:10], i["due"], i["status"], l["description"], f"{l['qty']:g}",
                            f"{l['price_cents'] / 100:.2f}", f"{amt:.2f}", cfg["tax_name"], f"{amt * cfg['tax_rate']:.2f}"])
        return Response(buf.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=acb-invoices.csv"})

    @app.get("/acb/invoices/{iid}")
    def invoice_view(iid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        i = DB.one("SELECT * FROM acb_invoices WHERE id = %s", (iid,))
        if not i:
            return page("Not found", "<p>No such invoice.</p>", user, csrf)
        link = str(request.base_url).rstrip("/") + f"/i/{i['token']}"
        btn = lambda s, label: f'<form method="post" action="/acb/invoices/{iid}/status" class="inline">{hidden(csrf)}<input type="hidden" name="status" value="{s}"><button>{label}</button></form>'
        acts = btn("sent", "Mark sent") if i["status"] == "draft" else (btn("paid", "Mark paid") if i["status"] == "sent" else f'<span class="ok">Paid {esc(i["paid_at"])}</span>')
        return page(f"Invoice #{iid} · {i['status']}", f"""{invoice_html(i)}<div class="card"><b>Client link:</b> <code>{esc(link)}</code><br>{acts}
<p class="muted">Online card payments: connect Stripe (test mode in the lab) or Invoice Ninja later; mark paid here for e-transfer and cheques.</p></div>""", user, csrf)

    @app.post("/acb/invoices/{iid}/status")
    async def invoice_status(iid: int, request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        f = await form(request)
        if not c.check_csrf(t, f.get("csrf")) or f.get("status") not in ("sent", "paid"):
            return bad(user, csrf)
        DB.run("UPDATE acb_invoices SET status = %s, paid_at = %s WHERE id = %s", (f["status"], stamp() if f["status"] == "paid" else "", iid))
        c.audit(user["email"], f"acb_invoice_{f['status']}", str(iid))
        return RedirectResponse(f"/acb/invoices/{iid}", 303)

    @app.get("/i/{token}")
    def public_invoice(token: str):
        i = DB.one("SELECT * FROM acb_invoices WHERE token = %s AND status <> 'draft'", (token,))
        if not i:
            return page("Invoice", "<p>This invoice link isn't active.</p>")
        st = '<p class="ok">Paid — thank you!</p>' if i["status"] == "paid" else f'<p>Pay by Interac e-Transfer or contact us at {esc(cfg["phone"])}.</p>'
        return page(f"Invoice #{i['id']}", invoice_html(i) + st)

    # ---------- client communications
    @app.get("/acb/messages")
    def messages(request: Request):
        user, t, deny, csrf = guard(request, OFFICE)
        if deny:
            return deny
        tm = (today() + timedelta(days=1)).isoformat()
        rem = DB.all("""SELECT j.title, c.name, c.phone, c.email, p.address FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id
            JOIN acb_clients c ON c.id = p.client_id WHERE j.day = %s AND j.status = 'scheduled' ORDER BY c.name""", (tm,))
        since = (today() - timedelta(days=7)).isoformat()
        rev = DB.all("""SELECT j.title, j.completed_at, c.name, c.phone, c.email FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id
            JOIN acb_clients c ON c.id = p.client_id WHERE j.status = 'done' AND j.completed_at >= %s ORDER BY j.completed_at DESC""", (since,))

        def links(phone, email, subject, body):
            out = []
            if phone:
                out.append(f'<a href="sms:{esc(re.sub(r"[^0-9+]", "", phone))}?&body={urlq(body)}">Text</a>')
            if email:
                out.append(f'<a href="mailto:{esc(email)}?subject={urlq(subject)}&body={urlq(body)}">Email</a>')
            return " · ".join(out) or '<span class="muted">no contact</span>'
        r1 = ""
        for r in rem:
            body = f"Hi {r['name'].split()[0]}, this is {cfg['company']}. Reminder: we're scheduled for {r['title']} at {r['address']} tomorrow. Reply if anything changes. Thank you!"
            r1 += f'<tr><td>{esc(r["name"])}<div class="muted">{esc(r["title"])}</div></td><td>{esc(body)}</td><td>{links(r["phone"], r["email"], "Visit tomorrow", body)}</td></tr>'
        r2 = ""
        for r in rev:
            ask = f" If you have a minute, a Google review helps us a lot: {cfg['review_url']}" if cfg["review_url"] else ""
            body = f"Hi {r['name'].split()[0]}, thanks for choosing {cfg['company']}! Your {r['title']} is done.{ask}"
            r2 += f'<tr><td>{esc(r["name"])}<div class="muted">{esc(r["completed_at"])}</div></td><td>{esc(body)}</td><td>{links(r["phone"], r["email"], "Thank you", body)}</td></tr>'
        return page("Messages to send", f"""<p class="muted">The lab sends nothing by itself: each link opens a ready-to-send text or email on your phone.</p>
<div class="card"><h2>Tomorrow's reminders</h2><table>{r1 or '<tr><td>No visits tomorrow.</td></tr>'}</table></div>
<div class="card"><h2>Thank-you + review requests (last 7 days)</h2><table>{r2 or '<tr><td>No finished jobs this week.</td></tr>'}</table></div>""", user, csrf)

    # ---------- client portal
    @app.get("/acb/my")
    def my(request: Request):
        user, t, deny, csrf = guard(request, None)
        if deny:
            return deny
        cl = DB.one("SELECT id, name FROM acb_clients WHERE email = %s ORDER BY id DESC LIMIT 1", (user["email"],))
        if not cl:
            return page("My account", "<p>We couldn't find your client record yet. Contact us and we'll link it.</p>", user, csrf)
        base = str(request.base_url).rstrip("/")
        qs = "".join(f'<li><a href="{base}/q/{q["token"]}">Quote #{q["id"]}</a> — {esc(q["status"])}</li>' for q in DB.all("SELECT id, token, status FROM acb_quotes WHERE client_id = %s AND status <> 'draft' ORDER BY id DESC", (cl["id"],)))
        ivs = "".join(f'<li><a href="{base}/i/{i["token"]}">Invoice #{i["id"]}</a> — {esc(i["status"])}</li>' for i in DB.all("SELECT id, token, status FROM acb_invoices WHERE client_id = %s AND status <> 'draft' ORDER BY id DESC", (cl["id"],)))
        up = "".join(f'<li>{esc(j["day"])} — {esc(j["title"])}</li>' for j in DB.all("""SELECT j.day, j.title FROM acb_jobs j JOIN acb_properties p ON p.id = j.property_id
            WHERE p.client_id = %s AND j.status = 'scheduled' AND j.day >= %s ORDER BY j.day LIMIT 10""", (cl["id"], today().isoformat())))
        return page(f"Hi {cl['name']}", f'<div class="card"><h2>Upcoming visits</h2><ul>{up or "<li>None booked.</li>"}</ul></div><div class="card"><h2>Quotes</h2><ul>{qs or "<li>None.</li>"}</ul></div><div class="card"><h2>Invoices</h2><ul>{ivs or "<li>None.</li>"}</ul></div>', user, csrf)
