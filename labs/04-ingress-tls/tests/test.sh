#!/usr/bin/env bash
# Run from the repo root:  bash labs/04-ingress-tls/tests/test.sh
set -uo pipefail
NS=lab-04-ingress-tls; pass=0; fail=0
ok()  { echo "PASS  $1"; pass=$((pass+1)); }
bad() { echo "FAIL  $1"; fail=$((fail+1)); }
expect_ok()   { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
expect_fail() { if eval "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }

IP=$(kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
expect_ok   "certificate issued by lab-ca"       "kubectl -n $NS wait --for=condition=Ready certificate/hello-tls --timeout=90s"
expect_ok   "https://hello.lab.local answers"    "curl -sk -m 5 --resolve hello.lab.local:443:$IP https://hello.lab.local | grep -q Hostname"
expect_fail "NodePort Service is refused"        "kubectl apply --dry-run=server -f labs/04-ingress-tls/tests/nodeport-service.yaml"
echo "----"; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
