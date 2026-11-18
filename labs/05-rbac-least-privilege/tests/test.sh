#!/usr/bin/env bash
# Run from the repo root:  bash labs/05-rbac-least-privilege/tests/test.sh
set -uo pipefail
NS=lab-05-rbac-least-privilege; pass=0; fail=0
ok()  { echo "PASS  $1"; pass=$((pass+1)); }
bad() { echo "FAIL  $1"; fail=$((fail+1)); }
expect_ok()   { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
expect_fail() { if eval "$2" >/dev/null 2>&1; then bad "$1"; else ok "$1"; fi; }

SA=system:serviceaccount:$NS:config-reader; APP=system:serviceaccount:$NS:app
expect_ok   "reader can get configmap/app-config"   "[ \"\$(kubectl auth can-i get configmap/app-config -n $NS --as=$SA)\" = yes ]"
expect_fail "reader cannot list configmaps"          "[ \"\$(kubectl auth can-i list configmaps -n $NS --as=$SA)\" = yes ]"
expect_fail "reader cannot read secrets"             "[ \"\$(kubectl auth can-i get secrets -n $NS --as=$SA)\" = yes ]"
expect_fail "reader cannot see other namespaces"     "[ \"\$(kubectl auth can-i get pods -n kube-system --as=$SA)\" = yes ]"
expect_fail "app SA cannot read configmaps"         "[ \"\$(kubectl auth can-i get configmaps -n $NS --as=$APP)\" = yes ]"
expect_fail "app SA cannot read secrets"            "[ \"\$(kubectl auth can-i get secrets -n $NS --as=$APP)\" = yes ]"
expect_fail "no cluster-wide binding for this ns"   "kubectl get clusterrolebindings -o jsonpath='{range .items[*]}{.subjects[*].namespace}{\"\\n\"}{end}' | grep -qw $NS"
echo "----"; echo "$pass passed, $fail failed"; [ "$fail" -eq 0 ]
