#!/usr/bin/env bash
# Turns on Velero backups to S3. Asks for the IAM access key (typed, never shown, never saved to disk in plain text).
#   bash scripts/setup-velero.sh cloudkanata-homelab-backups ca-central-1
set -euo pipefail
BUCKET="${1:?usage: setup-velero.sh <bucket> <region>}"; REGION="${2:?usage: setup-velero.sh <bucket> <region>}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$REPO_DIR/ansible/kubeconfig-lab}"
OUT="$REPO_DIR/platform/velero/sealedsecret.yaml"
command -v kubeseal >/dev/null || { echo "kubeseal missing - see labs/03-sealed-secrets/README.md"; exit 1; }
[ -f "$OUT" ] && { echo "$OUT exists already (delete it to rotate keys)"; exit 1; }
read -rp  "AWS access key ID for the velero IAM user: " AK
read -rsp "AWS secret access key (hidden): " SK; echo
CREDS="$(printf '[default]\naws_access_key_id=%s\naws_secret_access_key=%s\n' "$AK" "$SK")"
kubectl create secret generic velero-aws-credentials -n velero --from-literal=cloud="$CREDS" \
  --dry-run=client -o yaml | kubeseal -o yaml > "$OUT"
unset AK SK CREDS
grep -q "kind: SealedSecret" "$OUT" || { rm -f "$OUT"; echo "sealing failed"; exit 1; }
sed -i 's|^resources: \[\]|resources:\n  - sealedsecret.yaml|' "$REPO_DIR/platform/velero/kustomization.yaml"
sed -e "s|BUCKET_NAME|$BUCKET|" -e "s|BUCKET_REGION|$REGION|" \
  "$REPO_DIR/clusters/lab/optional/14-velero.yaml" > "$REPO_DIR/clusters/lab/apps/14-velero.yaml"
echo "Velero enabled for s3://$BUCKET ($REGION). Nightly backup 2:30 AM, kept 30 days."
echo "Next: git add -A && git commit -m 'velero: on' && git push"
echo "Then test:  velero backup create first-test --wait   (velero CLI: see docs/aws-velero.md)"
