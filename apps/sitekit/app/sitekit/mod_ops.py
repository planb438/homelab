"""CloudKanata operations panel: tenant directory (one namespace per project or client), safe lifecycle
buttons that call the Kubernetes API (quotas, suspend/resume, quarantine, soft delete with a grace period),
read-only support view, node status, billing status via signed webhook, and an append-only action log.
Every destructive action needs the tenant's exact name typed in. The cluster itself only lets this app touch
namespaces labelled cloudkanata.io/tenant (see the ValidatingAdmissionPolicy in the overlay)."""
import hashlib, hmac, json, re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import Request
from fastapi.responses import RedirectResponse, Response, JSONResponse
from .k8s import Kube, K8sError

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS ops_tenants (id SERIAL PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE NOT NULL, contact TEXT NOT NULL DEFAULT '',
        email TEXT NOT NULL DEFAULT '', plan TEXT NOT NULL DEFAULT 'small', cpu TEXT NOT NULL, memory TEXT NOT NULL, storage TEXT NOT NULL,
        pods INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'active', billing TEXT NOT NULL DEFAULT 'ok', notes TEXT NOT NULL DEFAULT '',
        created TEXT NOT NULL, delete_after TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '')""",
    """CREATE TABLE IF NOT EXISTS ops_log (id SERIAL PRIMARY KEY, at TEXT NOT NULL, admin TEXT NOT NULL, action TEXT NOT NULL,
        target TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', result TEXT NOT NULL DEFAULT 'ok')""",
]
PLANS = {"small": ("1", "1Gi", "5Gi", 10), "medium": ("2", "2Gi", "10Gi", 20), "large": ("4", "4Gi", "20Gi", 40)}
LABEL = "cloudkanata.io/tenant"


def register(c, kube=None):
    S, DB, esc, page, need = c.S, c.DB, c.esc, c.page, c.need
    cfg = {"timezone": "America/Toronto", "grace_days": 14, "grafana_url": "", "billing_url": "", "webhook_secret": "",
           "ingress_namespace": "traefik", **S.module_config.get("ops", {})}
    import os
    cfg["webhook_secret"] = os.environ.get("OPS_WEBHOOK_SECRET", cfg["webhook_secret"])
    TZ = ZoneInfo(cfg["timezone"])
    K = kube or Kube()
    ADMIN = {"admin"}
    VIEW = set(S.staff_roles)
    DB.migrate(SCHEMA)
    c.NAV.extend([("Tenants", "/ops", VIEW), ("Nodes", "/ops/nodes", VIEW), ("Action log", "/ops/log", VIEW)])
    app = c.app

    def stamp():
        return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")

    def log(user, action, target, payload=None, result="ok"):
        # append-only: the app never updates or deletes rows in ops_log
        DB.run("INSERT INTO ops_log (at, admin, action, target, payload, result) VALUES (%s, %s, %s, %s, %s, %s)",
               (stamp(), user, action, target, json.dumps(payload or {}, sort_keys=True)[:4000], result[:500]))

    def ns(slug):
        return f"t-{slug}"

    def tenant(slug):
        return DB.one("SELECT * FROM ops_tenants WHERE slug = %s", (slug,))

    async def form(request):
        return {k: str(v).strip() for k, v in (await request.form()).items()}

    def hidden(csrf):
        return f'<input type="hidden" name="csrf" value="{csrf}">'

    def typed(f, t):
        return f.get("confirm", "") == t["slug"]

    # ---- desired state for a tenant namespace (re-applied on every change, so it can't drift)
    def namespace_obj(t, extra_labels=None):
        labels = {LABEL: t["slug"], "app.kubernetes.io/managed-by": "sitekit-ops",
                  "pod-security.kubernetes.io/enforce": "restricted", "pod-security.kubernetes.io/warn": "restricted"}
        labels.update(extra_labels or {})
        return {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": ns(t["slug"]), "labels": labels,
                "annotations": {"cloudkanata.io/contact": t["email"], "cloudkanata.io/plan": t["plan"]}}}

    def quota_obj(t, suspended=False):
        return {"apiVersion": "v1", "kind": "ResourceQuota", "metadata": {"name": "tenant-quota"},
                "spec": {"hard": {"requests.cpu": t["cpu"], "limits.cpu": t["cpu"], "requests.memory": t["memory"], "limits.memory": t["memory"],
                                  "requests.storage": t["storage"], "pods": "0" if suspended else str(t["pods"]),
                                  "services.loadbalancers": "0", "services.nodeports": "0"}}}

    def limits_obj():
        return {"apiVersion": "v1", "kind": "LimitRange", "metadata": {"name": "tenant-defaults"},
                "spec": {"limits": [{"type": "Container", "default": {"cpu": "250m", "memory": "256Mi"},
                                     "defaultRequest": {"cpu": "50m", "memory": "64Mi"}, "max": {"cpu": "2", "memory": "2Gi"}}]}}

    def netpols(quarantine=False):
        base = [{"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "tenant-isolation"},
                 "spec": {"podSelector": {}, "policyTypes": ["Ingress"],
                          "ingress": [{"from": [{"podSelector": {}},
                                                {"namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": cfg["ingress_namespace"]}}}]}]}}]
        if quarantine:
            base.append({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "quarantine"},
                         "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"], "ingress": [], "egress": []}})
        return base

    def apply_tenant(t, suspended=None, quarantine=None):
        n = ns(t["slug"])
        suspended = t["status"] in ("suspended", "deleted") if suspended is None else suspended
        quarantine = t["status"] in ("quarantined", "deleted") if quarantine is None else quarantine
        extra = {"cloudkanata.io/state": t["status"]}
        if t["delete_after"]:
            extra["cloudkanata.io/delete-after"] = t["delete_after"]
        K.apply("/api/v1/namespaces", namespace_obj(t, extra))
        K.apply(f"/api/v1/namespaces/{n}/resourcequotas", quota_obj(t, suspended))
        K.apply(f"/api/v1/namespaces/{n}/limitranges", limits_obj())
        for p in netpols(quarantine):
            K.apply(f"/apis/networking.k8s.io/v1/namespaces/{n}/networkpolicies", p)
        if not quarantine:
            try:
                K.delete(f"/apis/networking.k8s.io/v1/namespaces/{n}/networkpolicies/quarantine")
            except K8sError as e:
                if e.status != 404:
                    raise

    def scale_all(t, to_zero):
        n = ns(t["slug"]); changed = []
        for kind in ("deployments", "statefulsets"):
            for obj in K.get(f"/apis/apps/v1/namespaces/{n}/{kind}").get("items", []):
                name = obj["metadata"]["name"]; ann = obj["metadata"].get("annotations", {}) or {}
                if to_zero:
                    cur = obj["spec"].get("replicas", 1)
                    if cur == 0:
                        continue
                    K.patch(f"/apis/apps/v1/namespaces/{n}/{kind}/{name}", {"metadata": {"annotations": {"cloudkanata.io/replicas": str(cur)}}, "spec": {"replicas": 0}})
                    changed.append(f"{kind}/{name}:{cur}->0")
                else:
                    back = int(ann.get("cloudkanata.io/replicas", "1"))
                    K.patch(f"/apis/apps/v1/namespaces/{n}/{kind}/{name}", {"spec": {"replicas": back}})
                    changed.append(f"{kind}/{name}:0->{back}")
        return changed

    def run(user, action, t, fn, payload=None):
        try:
            out = fn()
            DB.run("UPDATE ops_tenants SET last_error = '' WHERE slug = %s", (t["slug"],))
            log(user["email"], action, t["slug"], {**(payload or {}), "changed": out if isinstance(out, list) else None})
            return True
        except K8sError as e:
            DB.run("UPDATE ops_tenants SET last_error = %s WHERE slug = %s", (f"{stamp()} {action}: {e}"[:500], t["slug"]))
            log(user["email"], action, t["slug"], payload, f"error {e}")
            return False

    def live(t):
        if not K.ok:
            return None
        try:
            n = ns(t["slug"])
            pods = K.get(f"/api/v1/namespaces/{n}/pods").get("items", [])
            q = K.get(f"/api/v1/namespaces/{n}/resourcequotas/tenant-quota").get("status", {})
            ev = [e for e in K.get(f"/api/v1/namespaces/{n}/events").get("items", []) if e.get("type") == "Warning"][-10:]
            return {"pods": pods, "quota": q, "events": ev}
        except K8sError as e:
            return {"error": str(e)}

    # ---------- pages
    @app.get("/ops")
    def directory(request: Request):
        user, t, deny = need(request, VIEW)
        if deny:
            return deny
        csrf = c.csrf_for(t)
        rows = DB.all("SELECT * FROM ops_tenants ORDER BY status = 'deleted', name")
        tr = "".join(f"""<tr><td><a href="/ops/t/{esc(r['slug'])}"><b>{esc(r['name'])}</b></a><div class="muted">{esc(r['contact'])} {esc(r['email'])}</div></td>
<td><code>{ns(r['slug'])}</code></td><td>{esc(r['plan'])}: {esc(r['cpu'])} CPU · {esc(r['memory'])} RAM · {esc(r['storage'])} disk · {r['pods']} pods</td>
<td><span class="pill">{esc(r['status'])}</span>{'<div class="err">needs attention</div>' if r['last_error'] else ''}</td><td><span class="pill">{esc(r['billing'])}</span></td></tr>""" for r in rows)
        links = " · ".join(x for x in [f'<a href="{esc(cfg["grafana_url"])}" target="_blank">Grafana</a>' if cfg["grafana_url"] else "",
                                       f'<a href="{esc(cfg["billing_url"])}" target="_blank">Billing</a>' if cfg["billing_url"] else ""] if x)
        k = "" if K.ok else '<p class="err">Not connected to the cluster (running outside Kubernetes): changes are recorded but not applied.</p>'
        new = "" if user["role"] not in ADMIN else f"""<form method="post" action="/ops/tenants" class="card"><h2>Add tenant</h2>{hidden(csrf)}
<label>Name</label><input name="name" required><label>Short id (lowercase, becomes namespace t-&lt;id&gt;)</label><input name="slug" pattern="[a-z0-9][a-z0-9-]{{1,28}}[a-z0-9]" required>
<label>Contact name</label><input name="contact"><label>Contact email</label><input name="email" type="email">
<label>Plan</label><select name="plan">{''.join(f'<option>{p}</option>' for p in PLANS)}</select><button>Create tenant</button></form>"""
        return page("Tenants", f"""{k}<p>{links}</p><div class="card"><table><tr><th>Tenant</th><th>Namespace</th><th>Quota</th><th>Status</th><th>Billing</th></tr>
{tr or '<tr><td>No tenants yet.</td></tr>'}</table></div>{new}""", user, csrf)

    @app.post("/ops/tenants")
    async def create(request: Request):
        user, t, deny = need(request, ADMIN)
        if deny:
            return deny
        f = await form(request)
        slug = f.get("slug", "").lower()
        if not c.check_csrf(t, f.get("csrf")) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,28}[a-z0-9]", slug) or f.get("plan") not in PLANS or tenant(slug):
            return page("Check the form", '<p class="err">Use a unique short id (3–30 lowercase letters, numbers or dashes) and pick a plan.</p><p><a href="/ops">Back</a></p>', user, c.csrf_for(t))
        cpu, mem, disk, pods = PLANS[f["plan"]]
        DB.run("INSERT INTO ops_tenants (name, slug, contact, email, plan, cpu, memory, storage, pods, created) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
               (f.get("name", slug)[:80], slug, f.get("contact", "")[:80], f.get("email", "").lower()[:120], f["plan"], cpu, mem, disk, pods, stamp()))
        tn = tenant(slug)
        run(user, "tenant_create", tn, lambda: apply_tenant(tn), {"plan": f["plan"]})
        return RedirectResponse(f"/ops/t/{slug}", 303)

    @app.get("/ops/t/{slug}")
    def detail(slug: str, request: Request):
        user, t, deny = need(request, VIEW)
        if deny:
            return deny
        csrf = c.csrf_for(t)
        tn = tenant(slug)
        if not tn:
            return page("Not found", "<p>No such tenant.</p>", user, csrf)
        lv = live(tn)
        if lv is None:
            support = '<p class="muted">Live view needs the cluster connection.</p>'
        elif "error" in lv:
            support = f'<p class="err">{esc(lv["error"])}</p>'
        else:
            pods = "".join(f'<tr><td>{esc(p["metadata"]["name"])}</td><td>{esc(p.get("status", {}).get("phase", "?"))}</td><td>{sum(cs.get("restartCount", 0) for cs in p.get("status", {}).get("containerStatuses", []) or [])}</td></tr>' for p in lv["pods"])
            used, hard = lv["quota"].get("used", {}), lv["quota"].get("hard", {})
            qt = "".join(f'<tr><td>{esc(k)}</td><td>{esc(str(used.get(k, "0")))} / {esc(str(v))}</td></tr>' for k, v in sorted(hard.items()))
            ev = "".join(f'<li>{esc(e.get("reason", ""))}: {esc(e.get("message", "")[:200])}</li>' for e in lv["events"])
            support = f'<h3>Pods</h3><table>{pods or "<tr><td>None running.</td></tr>"}</table><h3>Quota used</h3><table>{qt}</table><h3>Recent warnings</h3><ul>{ev or "<li>None.</li>"}</ul>'
        err = f'<p class="err">Last error: {esc(tn["last_error"])}</p>' if tn["last_error"] else ""
        acts = ""
        if user["role"] in ADMIN:
            def act(action, label, danger=False, extra=""):
                conf = f'<input name="confirm" placeholder="type {esc(slug)} to confirm" required style="width:14rem">' if danger else ""
                return f'<form method="post" action="/ops/t/{esc(slug)}/{action}" class="card">{hidden(csrf)}{extra}{conf} <button{" style=background:#a12626" if danger else ""}>{label}</button></form>'
            st = tn["status"]
            plan_opts = "".join(f'<option{" selected" if p == tn["plan"] else ""}>{p}</option>' for p in PLANS)
            plan = f'<select name="plan" style="width:auto">{plan_opts}</select>'
            acts += act("resize", "Change plan (type name if it shrinks)", True, plan + " ")
            if st == "active":
                acts += act("suspend", "Suspend (scale to 0, keep data)", True)
                acts += act("quarantine", "Quarantine (cut all network)", True)
            if st == "suspended":
                acts += act("resume", "Resume")
            if st == "quarantined":
                acts += act("release", "Release quarantine")
            if st != "deleted":
                acts += act("delete", f"Delete (soft: suspended + isolated, removable after {cfg['grace_days']} days)", True)
            else:
                acts += act("restore", "Restore")
                ready = tn["delete_after"] and tn["delete_after"] <= datetime.now(TZ).strftime("%Y-%m-%d")
                acts += act("purge", "Purge now (deletes the namespace and its data)", True) if ready else f'<p class="muted">Can be purged after {esc(tn["delete_after"])}.</p>'
            acts += f'<p class="muted">Re-apply the tenant\'s guardrails (quota, limits, isolation) if someone changed them by hand:</p>{act("reconcile", "Reconcile")}'
        return page(f"{tn['name']} · {tn['status']}", f"""{err}<div class="card"><p>Namespace <code>{ns(slug)}</code> · plan {esc(tn['plan'])} ({esc(tn['cpu'])} CPU, {esc(tn['memory'])} RAM, {esc(tn['storage'])} disk, {tn['pods']} pods)
· billing <span class="pill">{esc(tn['billing'])}</span></p><p>{esc(tn['contact'])} {esc(tn['email'])}</p></div>
<div class="card"><h2>Support view (read-only)</h2>{support}</div>{acts}""", user, csrf)

    def action(name, needs_confirm, new_status=None):
        async def handler(slug: str, request: Request):
            user, t, deny = need(request, ADMIN)
            if deny:
                return deny
            f = await form(request)
            tn = tenant(slug)
            if not tn or not c.check_csrf(t, f.get("csrf")):
                return RedirectResponse("/ops", 303)
            shrink = name == "resize" and f.get("plan") in PLANS and list(PLANS).index(f["plan"]) < list(PLANS).index(tn["plan"])
            if (needs_confirm or shrink) and not typed(f, tn):
                log(user["email"], f"{name}_refused", slug, {"reason": "confirmation did not match"}, "refused")
                return page("Not confirmed", f'<p class="err">Type the tenant id exactly (<code>{esc(slug)}</code>) to confirm.</p><p><a href="/ops/t/{esc(slug)}">Back</a></p>', user, c.csrf_for(t))
            if name == "resize":
                if f.get("plan") not in PLANS:
                    return RedirectResponse(f"/ops/t/{slug}", 303)
                cpu, mem, disk, pods = PLANS[f["plan"]]
                DB.run("UPDATE ops_tenants SET plan = %s, cpu = %s, memory = %s, storage = %s, pods = %s WHERE slug = %s", (f["plan"], cpu, mem, disk, pods, slug))
                tn = tenant(slug)
                run(user, "resize", tn, lambda: apply_tenant(tn), {"plan": f["plan"]})
            elif name == "purge":
                if tn["status"] != "deleted" or not tn["delete_after"] or tn["delete_after"] > datetime.now(TZ).strftime("%Y-%m-%d"):
                    return RedirectResponse(f"/ops/t/{slug}", 303)
                if run(user, "purge", tn, lambda: K.delete(f"/api/v1/namespaces/{ns(slug)}")):
                    DB.run("UPDATE ops_tenants SET status = 'purged' WHERE slug = %s", (slug,))
                    DB.run("UPDATE ops_tenants SET slug = %s WHERE slug = %s", (f"{slug}-purged-{datetime.now(TZ).strftime('%Y%m%d%H%M')}", slug))
                return RedirectResponse("/ops", 303)
            else:
                st = new_status
                after = (datetime.now(TZ) + timedelta(days=int(cfg["grace_days"]))).strftime("%Y-%m-%d") if name == "delete" else ""
                DB.run("UPDATE ops_tenants SET status = %s, delete_after = %s WHERE slug = %s", (st, after if name == "delete" else "", slug))
                tn = tenant(slug)

                def go():
                    out = []
                    if name in ("suspend", "delete"):
                        out = scale_all(tn, True)
                    apply_tenant(tn)
                    if name in ("resume", "restore"):
                        out = scale_all(tn, False)
                    return out
                run(user, name, tn, go)
            return RedirectResponse(f"/ops/t/{slug}", 303)
        return handler

    for nm, conf, st in [("suspend", True, "suspended"), ("resume", False, "active"), ("quarantine", True, "quarantined"),
                         ("release", False, "active"), ("delete", True, "deleted"), ("restore", False, "active"), ("purge", True, None),
                         ("resize", False, None)]:
        app.post(f"/ops/t/{{slug}}/{nm}")(action(nm, conf, st))

    @app.post("/ops/t/{slug}/reconcile")
    async def reconcile(slug: str, request: Request):
        user, t, deny = need(request, ADMIN)
        if deny:
            return deny
        f = await form(request)
        tn = tenant(slug)
        if tn and c.check_csrf(t, f.get("csrf")):
            run(user, "reconcile", tn, lambda: apply_tenant(tn))
        return RedirectResponse(f"/ops/t/{slug}", 303)

    @app.get("/ops/nodes")
    def nodes(request: Request):
        user, t, deny = need(request, VIEW)
        if deny:
            return deny
        csrf = c.csrf_for(t)
        if not K.ok:
            return page("Nodes", '<p class="muted">Needs the cluster connection.</p>', user, csrf)
        try:
            items = K.get("/api/v1/nodes").get("items", [])
        except K8sError as e:
            return page("Nodes", f'<p class="err">{esc(str(e))}</p>', user, csrf)
        tr = ""
        for n in items:
            ready = next((x["status"] for x in n.get("status", {}).get("conditions", []) if x["type"] == "Ready"), "?")
            name = n["metadata"]["name"]
            sched = "cordoned" if n.get("spec", {}).get("unschedulable") else "schedulable"
            tr += f'<tr><td>{esc(name)}</td><td>{"Ready" if ready == "True" else "NOT ready"}</td><td>{sched}</td><td><code>kubectl drain {esc(name)} --ignore-daemonsets --delete-emptydir-data</code> · <code>kubectl uncordon {esc(name)}</code></td></tr>'
        return page("Nodes", f"""<div class="card"><table><tr><th>Node</th><th>Health</th><th>Scheduling</th><th>Maintenance (run from your desktop)</th></tr>{tr}</table></div>
<p class="muted">Draining moves every app off a node, so it stays a deliberate command you run yourself; this panel is read-only for nodes.</p>""", user, csrf)

    @app.get("/ops/log")
    def action_log(request: Request, fmt: str = ""):
        user, t, deny = need(request, VIEW)
        if deny:
            return deny
        rows = DB.all("SELECT * FROM ops_log ORDER BY id DESC LIMIT 500")
        if fmt == "json":
            return JSONResponse(rows)
        tr = "".join(f'<tr><td>{esc(r["at"])}</td><td>{esc(r["admin"])}</td><td>{esc(r["action"])}</td><td>{esc(r["target"])}</td><td><code>{esc(r["payload"][:200])}</code></td><td>{esc(r["result"])}</td></tr>' for r in rows)
        return page("Action log", f'<p><a href="/ops/log?fmt=json">Export JSON</a> · append-only</p><div class="card"><table><tr><th>When</th><th>Who</th><th>Action</th><th>Tenant</th><th>Details</th><th>Result</th></tr>{tr}</table></div>', user, c.csrf_for(t))

    @app.post("/ops/hooks/billing")
    async def billing_hook(request: Request):
        raw = await request.body()
        sig = request.headers.get("x-ops-signature", "")
        if not cfg["webhook_secret"] or not hmac.compare_digest(hmac.new(cfg["webhook_secret"].encode(), raw, hashlib.sha256).hexdigest(), sig):
            return JSONResponse({"error": "bad signature"}, 401)
        try:
            body = json.loads(raw)
        except ValueError:
            return JSONResponse({"error": "bad json"}, 400)
        slug, status = str(body.get("tenant", "")), str(body.get("status", ""))
        if status not in ("ok", "past_due", "cancelled") or not tenant(slug):
            return JSONResponse({"error": "unknown tenant or status"}, 400)
        DB.run("UPDATE ops_tenants SET billing = %s WHERE slug = %s", (status, slug))
        log("billing-webhook", "billing_status", slug, {"status": status})
        return {"ok": True}
