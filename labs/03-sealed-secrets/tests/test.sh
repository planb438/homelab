#!/usr/bin/env bash
# Run from the repo root:  bash labs/03-sealed-secrets/tests/test.sh
set -uo pipefail
NS=lab-03-sealed-secrets; pass=0; fail=0
ok()  { echo "PASS  $1"; pass=$((pass+1)); }
bad() { echo "FAIL  $1"; fail=$((fail+1)); }
expect_ok()   { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
expect_fail() { if eval "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }

expect_ok   "sealed-secrets controller running"     "kubectl -n kube-system get deploy sealed-secrets-controller"
expect_ok   "SealedSecret committed and unsealed"   "kubectl -n $NS get secret app-credentials"
expect_ok   "app sees the secret"                   "kubectl -n $NS logs deploy/app --tail=1 | grep -q loaded"
expect_fail "no plaintext Secret files in Git"      "grep -rlE '^kind: Secret$' apps labs platform --include=*.yaml"
echo "----"; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
