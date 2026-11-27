import importlib, json, re
import pytest
from fastapi.testclient import TestClient


def make(tmp_path, monkeypatch, modules, extra=None):
    site = tmp_path / "site"; site.mkdir(); (site / "index.html").write_text("<h1>LIVE</h1>")
    env = {"SITE_ROOT": str(site), "DATABASE_URL": f"sqlite:///{tmp_path}/t.db", "ADMIN_EMAIL": "admin@example.com",
           "ADMIN_PASSWORD": "admin-password-123", "SECURE_COOKIES": "false", "MODULES": modules, **(extra or {})}
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import sitekit.main as m
    importlib.reload(m)
    return TestClient(m.app)


def csrf(html):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def login(c, email, pw):
    from sitekit import security
    r = c.post("/app/login", data={"email": email, "password": pw, "next": "/app"}, follow_redirects=False)
    if "/2fa" in r.headers.get("location", ""):
        raise AssertionError("2fa")
    return r


def admin(c):
    from sitekit import security
    login(c, "admin@example.com", "admin-password-123")
    r = c.get("/app/account/2fa")
    s = re.search(r'name="secret" value="([A-Z2-7]+)"', r.text).group(1)
    c.post("/app/account/2fa", data={"secret": s, "code": security.totp_code(s), "csrf": csrf(r.text)})


def invite(c, role):
    r = c.get("/app/users")
    loc = c.post("/app/users/invite", data={"role": role, "note": role, "csrf": csrf(r.text)}, follow_redirects=False).headers["location"]
    return loc.split("t=")[1]


def register(c, t, email):
    c.post("/app/register", data={"t": t, "name": email.split("@")[0], "email": email, "password": "long-password-1"})


@pytest.fixture()
def c(tmp_path, monkeypatch):
    return make(tmp_path, monkeypatch, "acb", {"ROLES": '["admin","staff","crew","client"]',
        "FORMS": json.dumps({"quote": {"title": "Quote", "fields": [["name", "Name", True], ["phone", "Phone", True], ["email", "Email", True], ["address", "Address", True], ["service", "Service", True], ["details", "Details", False]]}})})


def test_full_acb_flow(c):
    # website request -> lead
    c.post("/app/forms/quote", data={"name": "Pat Doe", "phone": "416-555-0101", "email": "pat@x.com", "address": "12 Elm St, Toronto ON M4C 1A1", "service": "Lawn", "details": "weekly"})
    admin(c)
    h = c.get("/acb/clients").text
    c.post("/acb/clients/import", data={"csrf": csrf(h)})
    h = c.get("/acb/clients").text
    assert "Pat Doe" in h and "lead (1)" in h
    cid = int(re.search(r'/acb/clients/(\d+)"', h).group(1))
    h = c.get(f"/acb/clients/{cid}").text
    assert "M4C" in h
    pid = int(re.search(r"/acb/quotes/new\?property=(\d+)", h).group(1))
    # quote with catalog service, weekly
    h = c.get(f"/acb/quotes/new?property={pid}").text
    sid = re.search(r'<option value="(\d+)">Weekly lawn mowing', h).group(1)
    r = c.post("/acb/quotes", data={"csrf": csrf(h), "property_id": pid, "svc0": sid, "qty0": "1", "price0": "", "recurrence": "weekly", "notes": "Thanks"}, follow_redirects=False)
    qid = r.headers["location"].rsplit("/", 1)[1]
    h = c.get(f"/acb/quotes/{qid}").text
    assert "$45.00" in h and "$50.85" in h  # 45 + 13% HST
    c.post(f"/acb/quotes/{qid}/send", data={"csrf": csrf(h)})
    token = re.search(r"/q/([A-Za-z0-9_-]+)", c.get(f"/acb/quotes/{qid}").text).group(1)
    # client approves without logging in
    pub = TestClient(c.app)
    assert "Approve" in pub.get(f"/q/{token}").text
    pub.post(f"/q/{token}", data={"name": "Pat Doe", "agree": "1", "decision": "approve"})
    assert "approved" in pub.get(f"/q/{token}").text
    # job created, schedule it with a crew member
    t = invite(c, "crew")
    crew = TestClient(c.app); register(crew, t, "sam@crew.com"); login(crew, "sam@crew.com", "long-password-1")
    h = c.get(f"/acb/clients/{cid}").text
    jid = re.search(r'/acb/jobs/(\d+)"', h).group(1)
    h = c.get(f"/acb/jobs/{jid}").text
    crew_id = re.search(r'<option value="(\d+)">sam</option>', h).group(1)
    from sitekit.mod_acb import date
    c.post(f"/acb/jobs/{jid}", data={"csrf": csrf(h), "day": "2026-12-01", "crew_id": crew_id, "status": "scheduled", "recurrence": "weekly", "est_hours": "1", "price": "45", "notes": ""})
    assert "Elm St" in c.get("/acb/schedule?week=2026-12-01").text
    # crew: sees job, gate info, but no prices; clocks in, uploads photo, finishes
    jh = crew.get(f"/acb/jobs/{jid}").text
    assert "Elm St" in jh and "$" not in jh
    assert "can't open this page" in crew.get("/acb/invoices").text
    crew.post(f"/acb/jobs/{jid}/clock", data={"csrf": csrf(jh), "geo": "43.68,-79.29"})
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    crew.post(f"/acb/jobs/{jid}/photo", data={"csrf": csrf(jh), "kind": "after"}, files={"file": ("a.png", png, "image/png")})
    crew.post(f"/acb/jobs/{jid}/done", data={"csrf": csrf(jh)})
    h = c.get(f"/acb/jobs/{jid}").text
    assert "done" in h and "after photo" in h
    # recurring: next visit created a week later
    assert "2026-12-08" in c.get(f"/acb/clients/{cid}").text
    # invoice completed jobs, send, pay
    h = c.get(f"/acb/clients/{cid}").text
    r = c.post("/acb/invoices/from-jobs", data={"csrf": csrf(h), "client_id": cid}, follow_redirects=False)
    iid = r.headers["location"].rsplit("/", 1)[1]
    h = c.get(f"/acb/invoices/{iid}").text
    assert "$50.85" in h
    c.post(f"/acb/invoices/{iid}/status", data={"csrf": csrf(h), "status": "sent"})
    assert "Pat Doe" in c.get("/acb/invoices.csv").text
    itok = re.search(r"/i/([A-Za-z0-9_-]+)", c.get(f"/acb/invoices/{iid}").text).group(1)
    assert "Invoice #" in pub.get(f"/i/{itok}").text
    dash = c.get("/acb").text
    assert "Quote conversion" in dash and "100%" in dash
    assert "Thank you" in c.get("/acb/messages").text or "thanks for choosing" in c.get("/acb/messages").text


def test_crew_cannot_see_other_jobs(c):
    admin(c)
    h = c.get("/acb/clients").text
    r = c.post("/acb/clients", data={"csrf": csrf(h), "name": "Lee", "address": "1 Bay St M5J 2N8"}, follow_redirects=False)
    h = c.get(r.headers["location"]).text
    pid = re.search(r"/acb/jobs/new\?property=(\d+)", h).group(1)
    h = c.get(f"/acb/jobs/new?property={pid}").text
    r = c.post("/acb/jobs", data={"csrf": csrf(h), "property_id": pid, "title": "Salting", "day": "", "recurrence": "none", "est_hours": "1", "price": "35"}, follow_redirects=False)
    jid = r.headers["location"].rsplit("/", 1)[1]
    t = invite(c, "crew")
    crew = TestClient(c.app); register(crew, t, "kim@crew.com"); login(crew, "kim@crew.com", "long-password-1")
    assert "No such job on your list" in crew.get(f"/acb/jobs/{jid}").text
