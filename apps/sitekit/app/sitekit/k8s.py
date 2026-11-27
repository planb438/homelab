"""Tiny Kubernetes API client (stdlib only) using the pod's ServiceAccount token."""
import json, os, ssl, urllib.error, urllib.request

SA = "/var/run/secrets/kubernetes.io/serviceaccount"


class K8sError(Exception):
    def __init__(self, status, message):
        super().__init__(f"{status}: {message}")
        self.status = status


class Kube:
    def __init__(self):
        host, port = os.environ.get("KUBERNETES_SERVICE_HOST"), os.environ.get("KUBERNETES_SERVICE_PORT", "443")
        self.ok = bool(host) and os.path.exists(f"{SA}/token")
        if self.ok:
            self.base = f"https://{host}:{port}"
            self.ctx = ssl.create_default_context(cafile=f"{SA}/ca.crt")

    def call(self, method, path, body=None, ctype="application/json"):
        if not self.ok:
            raise K8sError(0, "not running in a cluster")
        with open(f"{SA}/token") as f:
            tok = f.read().strip()
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Authorization": f"Bearer {tok}", "Content-Type": ctype, "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, context=self.ctx, timeout=15) as r:
                raw = r.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            try:
                msg = json.loads(e.read()).get("message", e.reason)
            except Exception:
                msg = e.reason
            raise K8sError(e.code, msg)

    def get(self, path):
        return self.call("GET", path)

    def create(self, path, body):
        return self.call("POST", path, body)

    def patch(self, path, body):
        return self.call("PATCH", path, body, "application/merge-patch+json")

    def apply(self, path_collection, body):
        """create, or merge-patch if it already exists"""
        try:
            return self.create(path_collection, body)
        except K8sError as e:
            if e.status != 409:
                raise
            return self.patch(f"{path_collection}/{body['metadata']['name']}", body)

    def delete(self, path):
        return self.call("DELETE", path)
