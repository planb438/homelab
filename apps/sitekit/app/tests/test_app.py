import importlib, os, re, json
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    site = tmp_path / "site"; site.mkdir(); (site / "index.html").write_text("<h1>LIVE COPY</h1>")
    monkeypatch.setenv("SITE_ROOT", str(site))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/t.db")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin-password-123")
    monkeypatch.setenv("SECURE_COOKIES", "false")
    monkeypatch.setenv("FORMS", json.dumps({"quote": {"title": "Get a quote", "fields": [["name", "Name", True], ["email", "Email", True], ["details", "Details", False]]}}))
    monkeypatch.setenv("LAUNCHER", json.dumps([{"title": "HQ", "url": "https://example.com", "group": "Business"}]))
    import sitekit.main as m
    importlib.reload(m)
    return TestClient(m.app)


def login(c, email, pw):
    return c.post("/app/login", data={"email": email, "password": pw, "next": "/app"}, follow_redirects=False)


def enroll_2fa(c):
    from sitekit import security
    r = c.get("/app/account/2fa")
    secret = re.search(r'name="secret" value="([A-Z2-7]+)"', r.text).group(1)
    c.post("/app/account/2fa", data={"secret": secret, "code": security.totp_code(secret), "csrf": csrf(r.text)})
    return secret


def admin_in(c):
    assert login(c, "admin@example.com", "admin-password-123").status_code == 303
    return enroll_2fa(c)


def csrf(html):
    return re.search(r'name="csrf" value="([0-9a-f]+)"', html).group(1)


def test_site_served_and_health(client):
    assert "LIVE COPY" in client.get("/").text
    assert client.get("/healthz").text == "ok"


def test_app_requires_login(client):
    r = client.get("/app", follow_redirects=False)
    assert r.status_code == 303 and "/app/login" in r.headers["location"]


def test_bad_login_then_lockout(client):
    for _ in range(6):
        assert "Wrong email or password" in login(client, "admin@example.com", "nope").text
    assert "Too many tries" in login(client, "admin@example.com", "admin-password-123").text


def test_public_form_to_inbox_and_roles(client):
    r = client.post("/app/forms/quote", data={"name": "Sam", "email": "sam@x.com", "details": "snow plan"}, follow_redirects=False)
    assert r.status_code == 303
    assert login(client, "admin@example.com", "admin-password-123").status_code == 303
    assert "/app/account/2fa" in client.get("/app", follow_redirects=False).headers["location"]
    enroll_2fa(client)
    home = client.get("/app").text
    assert "1</b> new form submission" in home and "HQ" in home
    inbox = client.get("/app/inbox").text
    assert "snow plan" in inbox
    tok = csrf(inbox)
    assert client.post("/app/inbox/1", data={"status": "done", "note": "called", "csrf": "bad"}).text.count("expired") == 1
    client.post("/app/inbox/1", data={"status": "done", "note": "called", "csrf": tok})
    assert "called" in client.get("/app/inbox").text
    # invite a client, register, client cannot open inbox but sees own request
    users = client.get("/app/users").text
    r = client.post("/app/users/invite", data={"role": "client", "note": "Sam", "csrf": csrf(users)}, follow_redirects=False)
    link = r.headers["location"].split("link=")[1]
    t = link.split("t=")[1]
    client.cookies.clear()
    assert client.post("/app/register", data={"t": t, "name": "Sam", "email": "sam@x.com", "password": "short"}).text.count("10 characters") == 1
    assert client.post("/app/register", data={"t": t, "name": "Sam", "email": "sam@x.com", "password": "sam-password-123"}, follow_redirects=False).status_code == 303
    assert "expired or was already used" in client.get(f"/app/register?t={t}").text
    assert login(client, "sam@x.com", "sam-password-123").status_code == 303
    assert "Your requests" in client.get("/app").text and "quote" in client.get("/app").text
    assert "can't open this page" in client.get("/app/inbox").text
    assert "can't open this page" in client.get("/app/users").text
    assert "HQ" not in client.get("/app").text  # launcher is admin-only


def test_honeypot(client):
    client.post("/app/forms/quote", data={"name": "zz-honeypot", "email": "b@x.com", "website": "spam"})
    admin_in(client)
    assert "zz-honeypot" not in client.get("/app/inbox").text


def test_git_dir_hidden(client):
    assert client.get("/.git").status_code == 404


def test_two_step_login(client):
    from sitekit import security
    secret = admin_in(client)
    client.cookies.clear()
    r = login(client, "admin@example.com", "admin-password-123")
    assert "/app/login/2fa" in r.headers["location"]
    p = r.headers["location"].split("p=")[1]
    assert "match. Try the newest" in client.post("/app/login/2fa", data={"p": p, "code": "000000"}).text
    r = client.post("/app/login/2fa", data={"p": p, "code": security.totp_code(secret)}, follow_redirects=False)
    assert r.status_code == 303 and "Welcome" in client.get("/app").text


def test_totp_known_vector():
    from sitekit import security
    # RFC 6238 SHA-1 test secret "12345678901234567890", T=59 -> 94287082 (last 6 digits 287082)
    import base64
    s = base64.b32encode(b"12345678901234567890").decode()
    assert security.totp_code(s, 59) == "287082"
