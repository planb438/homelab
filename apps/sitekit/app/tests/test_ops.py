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

from sitekit.k8s import K8sError


def deep(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            deep(a[k], v)
        else:
            a[k] = v


class FakeKube:
    ok = True
    store = {}

    def __init__(self):
        FakeKube.store = {}
        self.store = FakeKube.store

    def get(self, path):
        if path in self.store:
            return self.store[path]
        items = [v for k, v in self.store.items() if k.rsplit("/", 1)[0] == path]
        if items or path.endswith(("pods", "events", "deployments", "statefulsets", "nodes")):
            return {"items": items}
        raise K8sError(404, "not found")

    def create(self, coll, body):
        p = f"{coll}/{body['metadata']['name']}"
        if p in self.store:
            raise K8sError(409, "exists")
        self.store[p] = json.loads(json.dumps(body)); return body

    def patch(self, path, body):
        if path not in self.store:
            raise K8sError(404, "nf")
        deep(self.store[path], body); return self.store[path]

    def apply(self, coll, body):
        try:
            return self.create(coll, body)
        except K8sError:
            return self.patch(f"{coll}/{body['metadata']['name']}", body)

    def delete(self, path):
        if self.store.pop(path, None) is None:
            raise K8sError(404, "nf")
        for k in [k for k in self.store if k.startswith(path.replace("/api/v1/namespaces/", "/api/v1/namespaces/") + "/")]:
            self.store.pop(k)


@pytest.fixture()
def c(tmp_path, monkeypatch):
    import sitekit.mod_ops as mo
    monkeypatch.setattr(mo, "Kube", FakeKube)
    monkeypatch.setenv("OPS_WEBHOOK_SECRET", "s3cret")
    return make(tmp_path, monkeypatch, "ops")


def test_ops_lifecycle(c):
    import hmac, hashlib
    admin(c)
    h = c.get("/ops").text
    c.post("/ops/tenants", data={"csrf": csrf(h), "name": "ACB Landscaping", "slug": "acb", "contact": "Chris", "email": "a@b.c", "plan": "small"})
    st = FakeKube.store
    nsobj = st["/api/v1/namespaces/t-acb"]
    assert nsobj["metadata"]["labels"]["cloudkanata.io/tenant"] == "acb"
    assert nsobj["metadata"]["labels"]["pod-security.kubernetes.io/enforce"] == "restricted"
    assert st["/api/v1/namespaces/t-acb/resourcequotas/tenant-quota"]["spec"]["hard"]["pods"] == "10"
    assert "/apis/networking.k8s.io/v1/namespaces/t-acb/networkpolicies/tenant-isolation" in st
    st["/apis/apps/v1/namespaces/t-acb/deployments/web"] = {"metadata": {"name": "web", "annotations": {}}, "spec": {"replicas": 2}}
    h = c.get("/ops/t/acb").text
    assert "Support view" in h
    # destructive action without typed name is refused and logged
    assert "Type the tenant id exactly" in c.post("/ops/t/acb/suspend", data={"csrf": csrf(h), "confirm": "nope"}).text
    c.post("/ops/t/acb/suspend", data={"csrf": csrf(h), "confirm": "acb"})
    assert st["/apis/apps/v1/namespaces/t-acb/deployments/web"]["spec"]["replicas"] == 0
    assert st["/api/v1/namespaces/t-acb/resourcequotas/tenant-quota"]["spec"]["hard"]["pods"] == "0"
    c.post("/ops/t/acb/resume", data={"csrf": csrf(h)})
    assert st["/apis/apps/v1/namespaces/t-acb/deployments/web"]["spec"]["replicas"] == 2
    c.post("/ops/t/acb/quarantine", data={"csrf": csrf(h), "confirm": "acb"})
    assert "/apis/networking.k8s.io/v1/namespaces/t-acb/networkpolicies/quarantine" in st
    c.post("/ops/t/acb/release", data={"csrf": csrf(h)})
    assert "/apis/networking.k8s.io/v1/namespaces/t-acb/networkpolicies/quarantine" not in st
    # shrinking the plan needs confirmation; growing doesn't
    c.post("/ops/t/acb/resize", data={"csrf": csrf(h), "plan": "large"})
    assert st["/api/v1/namespaces/t-acb/resourcequotas/tenant-quota"]["spec"]["hard"]["pods"] == "40"
    assert "Type the tenant id" in c.post("/ops/t/acb/resize", data={"csrf": csrf(h), "plan": "small"}).text
    # soft delete: suspended + isolated, purge not offered before the grace period
    c.post("/ops/t/acb/delete", data={"csrf": csrf(h), "confirm": "acb"})
    h = c.get("/ops/t/acb").text
    assert "Can be purged after" in h and "/api/v1/namespaces/t-acb" in st
    c.post("/ops/t/acb/purge", data={"csrf": csrf(h), "confirm": "acb"})
    assert "/api/v1/namespaces/t-acb" in st  # still there
    c.post("/ops/t/acb/restore", data={"csrf": csrf(h)})
    assert "active" in c.get("/ops").text
    # billing webhook: signed only
    body = json.dumps({"tenant": "acb", "status": "past_due"}).encode()
    assert c.post("/ops/hooks/billing", content=body, headers={"x-ops-signature": "bad"}).status_code == 401
    sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert c.post("/ops/hooks/billing", content=body, headers={"x-ops-signature": sig}).status_code == 200
    assert "past_due" in c.get("/ops").text
    log = c.get("/ops/log?fmt=json").json()
    actions = [r["action"] for r in log]
    assert "suspend_refused" in actions and "tenant_create" in actions and "billing_status" in actions


def test_staff_cannot_act(c):
    admin(c)
    t = invite(c, "staff")
    from fastapi.testclient import TestClient
    s = TestClient(c.app); register(s, t, "sue@x.com"); login(s, "sue@x.com", "long-password-1")
    assert "Tenants" in s.get("/ops").text and "Add tenant" not in s.get("/ops").text
    h = s.get("/ops").text
    assert "can't open this page" in s.post("/ops/tenants", data={"csrf": csrf(h), "name": "x", "slug": "xyz", "plan": "small"}).text
