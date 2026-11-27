#!/usr/bin/env python3
"""Harden the control-plane static pods. Idempotent.
kube-apiserver: encryption at rest, audit log (CIS 30 days / 10 files / 100 MB), profiling off.
kube-controller-manager + kube-scheduler: profiling off. Manifests keep mode 600 (CIS 1.1.x).
Backups go to /root/apiserver-backups, never inside /etc/kubernetes/manifests (a copy there would start a second pod)."""
import os, shutil, time, yaml

M = "/etc/kubernetes/manifests"
PLAN = {
    "kube-apiserver.yaml": {
        "flags": {
            "--encryption-provider-config": "/etc/kubernetes/enc/encryption-config.yaml",
            "--audit-policy-file": "/etc/kubernetes/audit/policy.yaml",
            "--audit-log-path": "/var/log/kubernetes/audit/audit.log",
            "--audit-log-maxage": "30",
            "--audit-log-maxbackup": "10",
            "--audit-log-maxsize": "100",
            "--profiling": "false",
        },
        "mounts": [("enc-config", "/etc/kubernetes/enc", True), ("audit-policy", "/etc/kubernetes/audit", True),
                   ("audit-log", "/var/log/kubernetes/audit", False)],
    },
    "kube-controller-manager.yaml": {"flags": {"--profiling": "false"}, "mounts": []},
    "kube-scheduler.yaml": {"flags": {"--profiling": "false"}, "mounts": []},
}
os.makedirs("/root/apiserver-backups", exist_ok=True)
any_change = False
for fname, plan in PLAN.items():
    path = os.path.join(M, fname)
    if not os.path.exists(path):
        continue
    doc = yaml.safe_load(open(path))
    c = doc["spec"]["containers"][0]
    cmd = c["command"]
    changed = False
    for k, v in plan["flags"].items():
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
    for name, mpath, ro in plan["mounts"]:
        if not any(m.get("name") == name for m in mounts):
            mounts.append({"name": name, "mountPath": mpath, "readOnly": ro})
            changed = True
        if not any(v.get("name") == name for v in vols):
            vols.append({"name": name, "hostPath": {"path": mpath, "type": "DirectoryOrCreate"}})
            changed = True
    if changed:
        backup = f"/root/apiserver-backups/{fname}.{int(time.time())}"
        shutil.copy2(path, backup)
        tmp = f"/etc/kubernetes/.{fname}.new"
        with open(tmp, "w") as f:
            yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
        print(f"BACKUP={backup}|{path}")
        any_change = True
    if os.stat(path).st_mode & 0o077:
        os.chmod(path, 0o600)
print("RESULT=CHANGED" if any_change else "RESULT=UNCHANGED")
