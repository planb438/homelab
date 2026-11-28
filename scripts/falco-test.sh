#!/usr/bin/env bash
# Prove Falco works: open a shell in a throwaway pod and read /etc/shadow, then show the alerts Falco raised.
set -euo pipefail
kubectl -n falco rollout status ds/falco --timeout=180s
kubectl create ns falco-test --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl -n falco-test run bait --image=busybox --restart=Never -- sleep 600 >/dev/null 2>&1 || true
kubectl -n falco-test wait --for=condition=Ready pod/bait --timeout=90s >/dev/null
NODE=$(kubectl -n falco-test get pod bait -o jsonpath='{.spec.nodeName}')
echo "== doing suspicious things in pod bait on $NODE"
kubectl -n falco-test exec bait -- sh -c 'cat /etc/shadow >/dev/null 2>&1; echo hi > /etc/evil' || true
kubectl -n falco-test exec -it bait -- sh -c 'exit' </dev/null || true
sleep 5
FPOD=$(kubectl -n falco get pod -l app.kubernetes.io/name=falco --field-selector spec.nodeName="$NODE" -o name | head -1)
echo "== Falco alerts from $FPOD (last 2 min)"
kubectl -n falco logs "$FPOD" -c falco --since=2m | grep -E '"rule"' | grep -i 'bait' \
  | python3 -c 'import sys,json
for l in sys.stdin:
    try: j=json.loads(l[l.index("{"):])
    except Exception: continue
    print(f"{j.get(\"priority\",\"\"):8} {j.get(\"rule\",\"\")}")' || echo "(no alerts yet: wait 30 s and re-run)"
kubectl delete ns falco-test --wait=false >/dev/null
