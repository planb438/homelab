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
    return make(tmp_path, monkeypatch, "qa", {"SELF_SIGNUP": "true", "MODULE_CONFIG": json.dumps({"qa": {"categories": ["Canada · Immigration", "Bahamas · Government"], "official_domains": ["canada.ca", "gov.bs"]}})})


def signup(cl, email):
    cl.post("/app/signup", data={"name": email.split("@")[0], "email": email, "password": "long-password-1", "next": "/qa"})


def test_qa_flow(c):
    from fastapi.testclient import TestClient
    asker = TestClient(c.app); signup(asker, "ann@x.com")
    h = asker.get("/qa/ask").text
    r = asker.post("/qa/ask", data={"csrf": csrf(h), "title": "How long does a work permit extension take?", "category": "Canada · Immigration",
                                    "body": "I applied in October from inside Canada. What is the usual time?", "tags": "work permit, ircc"}, follow_redirects=False)
    url = r.headers["location"]
    assert "pending=1" in url  # new member -> moderated
    anon = TestClient(c.app)
    assert "work permit" not in anon.get("/qa").text.lower()
    admin(c)
    h = c.get("/qa/moderate").text
    assert "work permit extension" in h
    qid = re.search(r"/qa/moderate/q/(\d+)", h).group(1)
    c.post(f"/qa/moderate/q/{qid}", data={"csrf": csrf(h), "state": "visible"})
    assert "work permit extension" in anon.get("/qa").text
    qurl = url.split("?")[0]
    h = c.get(qurl).text
    # official answer requires an official domain
    assert "official source" in c.post(f"/qa/{qid}/answer", data={"csrf": csrf(h), "body": "Check processing times on the official page.", "source_url": "https://example.com/x"}).text
    c.post(f"/qa/{qid}/answer", data={"csrf": csrf(h), "body": "Processing times change weekly; check the official tool.", "source_url": "https://www.canada.ca/en/immigration-refugees-citizenship/services/application/check-processing-times.html"})
    page = anon.get(qurl).text
    assert "Official answer" in page and "canada.ca" in page and "1 answer(s)" in page
    # asker votes and picks best answer
    h = asker.get(qurl).text
    aid = re.search(r'name="id" value="(\d+)"><button class="link">Select as best', h).group(1)
    asker.post("/qa/vote", data={"csrf": csrf(h), "kind": "a", "id": aid, "value": "1"})
    asker.post("/qa/best", data={"csrf": csrf(h), "id": aid})
    page = anon.get(qurl).text
    assert "Best answer" in page
    assert "Authority" in anon.get("/qa/users").text or "Member" in anon.get("/qa/users").text
    assert qurl in anon.get("/qa/sitemap.xml").text
    assert "work permit" in anon.get("/qa?tag=ircc").text.lower()
    assert "work permit" in anon.get("/qa?q=extension").text.lower()


def test_flags_hide(c):
    from fastapi.testclient import TestClient
    admin(c)
    h = c.get("/qa/ask").text
    r = c.post("/qa/ask", data={"csrf": csrf(h), "title": "Staff posted question about passports", "category": "Bahamas · Government", "body": "Where do I renew a Bahamian passport?", "tags": "passport"}, follow_redirects=False)
    qurl = r.headers["location"]; qid = re.search(r"/qa/(\d+)-", qurl).group(1)
    for i in range(3):
        u = TestClient(c.app); signup(u, f"f{i}@x.com")
        u.post("/qa/flag", data={"csrf": csrf(u.get(qurl).text), "kind": "q", "id": qid})
    assert "passport" not in TestClient(c.app).get("/qa").text.lower()
    assert "flagged" in c.get("/qa/moderate").text
