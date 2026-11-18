#!/usr/bin/env bash
# Run from the repo root:  bash labs/06-supply-chain/tests/test.sh
set -uo pipefail
NS=lab-06-supply-chain; pass=0; fail=0
ok()  { echo "PASS  $1"; pass=$((pass+1)); }
bad() { echo "FAIL  $1"; fail=$((fail+1)); }
expect_ok()   { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
expect_fail() { if eval "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }

D=labs/06-supply-chain/tests
expect_ok   "policy is ready"                 "kubectl -n $NS get policies.kyverno.io image-rules -o jsonpath='{.status.conditions[0].status}' | grep -q True"
expect_ok   "pinned nginxinc image runs"      "kubectl -n $NS wait --for=condition=Available deploy/web --timeout=60s"
expect_fail ":latest image refused"           "kubectl apply --dry-run=server -f $D/latest-tag-pod.yaml"
expect_fail "unknown registry refused"        "kubectl apply --dry-run=server -f $D/unknown-registry-pod.yaml"
echo "Digest audit report:"; kubectl -n $NS get policyreport -o wide 2>/dev/null | head -5
echo "----"; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
