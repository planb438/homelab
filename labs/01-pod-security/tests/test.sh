#!/usr/bin/env bash
# Run from the repo root:  bash labs/01-pod-security/tests/test.sh
set -uo pipefail
NS=lab-01-pod-security; pass=0; fail=0
ok()  { echo "PASS  $1"; pass=$((pass+1)); }
bad() { echo "FAIL  $1"; fail=$((fail+1)); }
expect_ok()   { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
expect_fail() { if eval "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }

D=labs/01-pod-security/tests
expect_ok   "hardened web pod is Ready"            "kubectl -n $NS wait --for=condition=Available deploy/web --timeout=60s"
expect_ok   "web runs as UID 101 (not root)"       "[ \"\$(kubectl -n $NS exec deploy/web -- id -u)\" = 101 ]"
expect_fail "privileged root pod is rejected"      "kubectl apply --dry-run=server -f $D/bad-root-pod.yaml"
expect_fail "hostPath + hostNetwork pod rejected"  "kubectl apply --dry-run=server -f $D/bad-hostpath-pod.yaml"
expect_fail "root filesystem is read-only"         "kubectl -n $NS exec deploy/web -- touch /etc/x"
echo "----"; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
