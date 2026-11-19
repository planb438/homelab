#!/usr/bin/env bash
# Creates the civic-hub passwords for one environment as a SealedSecret (safe to commit).
#   bash scripts/seal-civic-hub.sh dev      (then: git add, commit, push)
# The plain passwords never touch disk. Grafana admin password is printed ONCE - save it in your password manager.
set -euo pipefail
ENV="${1:?usage: seal-civic-hub.sh <dev|prod>}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$REPO_DIR/apps/civic-hub/overlays/$ENV/sealedsecret.yaml"
KUST="$REPO_DIR/apps/civic-hub/overlays/$ENV/kustomization.yaml"
export KUBECONFIG="${KUBECONFIG:-$REPO_DIR/ansible/kubeconfig-lab}"
command -v kubeseal >/dev/null || { echo "kubeseal missing - see labs/03-sealed-secrets/README.md step 1"; exit 1; }
[ -f "$KUST" ] || { echo "no overlay $ENV"; exit 1; }
[ -f "$OUT" ] && { echo "$OUT already exists - delete it first to rotate passwords"; exit 1; }
pw() { openssl rand -hex 24; }
GRAFANA_ADMIN="$(pw)"
kubectl create secret generic civic-hub-secrets -n "$ENV" \
  --from-literal=POSTGRES_PASSWORD="$(pw)" \
  --from-literal=GRAFANA_DB_PASSWORD="$(pw)" \
  --from-literal=GRAFANA_ADMIN_PASSWORD="$GRAFANA_ADMIN" \
  --dry-run=client -o yaml | kubeseal -o yaml > "$OUT"
sed -i 's|  # - sealedsecret.yaml.*|  - sealedsecret.yaml|' "$KUST"
echo "Wrote $OUT and enabled it in $KUST"
echo "Grafana login for $ENV:  admin / $GRAFANA_ADMIN   <- save this now, it is not stored anywhere else"
echo "Next: git add apps/civic-hub/overlays/$ENV && git commit -m 'civic-hub: $ENV secrets' && git push"
