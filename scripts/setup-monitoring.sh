#!/usr/bin/env bash
# Turns on cluster monitoring (Prometheus + Grafana): seals a Grafana admin password and enables the Argo CD app.
#   bash scripts/setup-monitoring.sh      then: git add -A && git commit -m "monitoring: on" && git push
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$REPO_DIR/ansible/kubeconfig-lab}"
OUT="$REPO_DIR/platform/monitoring/sealedsecret.yaml"
command -v kubeseal >/dev/null || { echo "kubeseal missing - see labs/03-sealed-secrets/README.md"; exit 1; }
[ -f "$OUT" ] && { echo "$OUT exists already (delete it to rotate the password)"; exit 1; }
PW="$(openssl rand -hex 20)"
kubectl create secret generic grafana-admin -n monitoring \
  --from-literal=admin-user=admin --from-literal=admin-password="$PW" \
  --dry-run=client -o yaml | kubeseal -o yaml > "$OUT"
grep -q "kind: SealedSecret" "$OUT" || { rm -f "$OUT"; echo "sealing failed"; exit 1; }
sed -i 's|^resources: \[\]|resources:\n  - sealedsecret.yaml|' "$REPO_DIR/platform/monitoring/kustomization.yaml"
cp "$REPO_DIR/clusters/lab/optional/13-monitoring.yaml" "$REPO_DIR/clusters/lab/apps/13-monitoring.yaml"
echo "Monitoring enabled. Grafana: https://grafana.lab.local  user: admin  password: $PW"
echo "Save the password in your password manager now. Add grafana.lab.local to /etc/hosts."
echo "Next: git add -A && git commit -m 'monitoring: on' && git push"
