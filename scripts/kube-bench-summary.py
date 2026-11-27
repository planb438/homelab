#!/usr/bin/env python3
"""Turn kube-bench JSON (reports/kube-bench/<stamp>/{before,after}/<node>.json) into SUMMARY.md."""
import json, os, sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")


def load(p):
    try:
        data = json.loads(p.read_text())
    except Exception:
        return None, {}
    controls = data.get("Controls", data if isinstance(data, list) else [])
    tot = {"PASS": 0, "FAIL": 0, "WARN": 0, "INFO": 0}
    res = {}
    for c in controls:
        for t in c.get("tests", []) or []:
            for r in t.get("results", []) or []:
                st = r.get("status", "INFO")
                tot[st] = tot.get(st, 0) + 1
                res[r.get("test_number", "?")] = (st, r.get("test_desc", ""), (r.get("remediation") or "").strip())
    return tot, res


phases = [p for p in ("before", "after") if (root / p).is_dir()]
nodes = sorted({f.stem for ph in phases for f in (root / ph).glob("*.json")})
lines = [f"# kube-bench report — {root.name}", "", "CIS Kubernetes Benchmark, run by `ansible/security.yml`.", "",
         "| Node | Phase | PASS | FAIL | WARN |", "| --- | --- | --- | --- | --- |"]
data = {}
for n in nodes:
    for ph in phases:
        tot, res = load(root / ph / f"{n}.json")
        data[(n, ph)] = res
        if tot is not None:
            lines.append(f"| {n} | {ph} | {tot['PASS']} | {tot['FAIL']} | {tot['WARN']} |")
if "before" in phases and "after" in phases:
    lines += ["", "## Fixed by this run", ""]
    fixed = []
    for n in nodes:
        b, a = data.get((n, "before"), {}), data.get((n, "after"), {})
        for k, (st, desc, _) in a.items():
            if st == "PASS" and b.get(k, ("",))[0] in ("FAIL", "WARN"):
                fixed.append(f"- **{n} {k}** {desc}")
    lines += fixed or ["- nothing changed"]
last = phases[-1] if phases else None
if last:
    lines += ["", f"## Still failing ({last})", ""]
    for n in nodes:
        fails = [(k, d, rem) for k, (st, d, rem) in sorted(data.get((n, last), {}).items()) if st == "FAIL"]
        if fails:
            lines.append(f"### {n}")
            for k, d, rem in fails:
                lines.append(f"- **{k}** {d}" + (f"  \n  _Fix:_ {rem.splitlines()[0][:220]}" if rem else ""))
            lines.append("")
lines += ["", "Some FAILs are expected in a lab (for example rules that need an external secret manager or",
          "settings kubeadm chooses on purpose). Treat this list as the backlog for the next hardening pass."]
out = root / "SUMMARY.md"
out.write_text("\n".join(lines) + "\n")
print(f"kube-bench summary: {out}")
for l in lines:
    if l.startswith("|"):
        print(l)
