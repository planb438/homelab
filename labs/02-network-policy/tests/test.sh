#!/usr/bin/env bash
# Run from the repo root:  bash labs/02-network-policy/tests/test.sh
set -uo pipefail
NS=lab-02-network-policy; pass=0; fail=0
ok()  { echo "PASS  $1"; pass=$((pass+1)); }
bad() { echo "FAIL  $1"; fail=$((fail+1)); }
expect_ok()   { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
expect_fail() { if eval "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }

for d in web client intruder; do kubectl -n $NS wait --for=condition=Available deploy/$d --timeout=60s >/dev/null; done
expect_ok   "client -> web:8080 allowed"           "kubectl -n $NS exec deploy/client -- curl -s -m 5 http://web:8080"
expect_fail "intruder -> web blocked"              "kubectl -n $NS exec deploy/intruder -- curl -s -m 5 http://web:8080"
expect_fail "client -> internet blocked (egress)"  "kubectl -n $NS exec deploy/client -- curl -s -m 5 https://example.com"
expect_ok   "DNS still works"                      "kubectl -n $NS exec deploy/client -- nslookup kubernetes.default 2>/dev/null || kubectl -n $NS exec deploy/client -- curl -s -m 5 -o /dev/null http://web:8080"
echo "----"; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
