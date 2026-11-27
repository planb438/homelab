#!/usr/bin/env python3
"""Add encryption-at-rest and audit-log flags + mounts to the kube-apiserver static pod. Idempotent.
Backs up the manifest outside /etc/kubernetes/manifests (a copy inside it would start a second API server)."""
import os, shutil, time, yaml

P = "/etc/kubernetes/manifests/kube-apiserver.yaml"
doc = yaml.safe_load(open(P))
c = doc["spec"]["containers"][0]
cmd = c["command"]
want = {
    "--encryption-provider-config": "/etc/kubernetes/enc/encryption-config.yaml",
    "--audit-policy-file": "/etc/kubernetes/audit/policy.yaml",
    "--audit-log-path": "/var/log/kubernetes/audit/audit.log",
    "--audit-log-maxage": "7",
    "--audit-log-maxbackup": "5",
    "--audit-log-maxsize": "50",
}
changed = False
for k, v in want.items():
    flag = f"{k}={v}"
    hits = [i for i, a in enumerate(cmd) if a.startswith(k + "=")]
    if hits:
        if cmd[hits[0]] != flag:
            cmd[hits[0]] = flag
            changed = True
    else:
        cmd.append(flag)
        changed = True
mounts = c.setdefault("volumeMounts", [])
vols = doc["spec"].setdefault("volumes", [])
for name, path, ro in [("enc-config", "/etc/kubernetes/enc", True), ("audit-policy", "/etc/kubernetes/audit", True),
                       ("audit-log", "/var/log/kubernetes/audit", False)]:
    if not any(m.get("name") == name for m in mounts):
        mounts.append({"name": name, "mountPath": path, "readOnly": ro})
        changed = True
    if not any(v.get("name") == name for v in vols):
        vols.append({"name": name, "hostPath": {"path": path, "type": "DirectoryOrCreate"}})
        changed = True
if changed:
    os.makedirs("/root/apiserver-backups", exist_ok=True)
    backup = f"/root/apiserver-backups/kube-apiserver.yaml.{int(time.time())}"
    shutil.copy2(P, backup)
    tmp = "/etc/kubernetes/.kube-apiserver.yaml.new"
    with open(tmp, "w") as f:
        yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)
    os.replace(tmp, P)
    print(f"BACKUP={backup}")
    print("CHANGED")
else:
    print("UNCHANGED")
