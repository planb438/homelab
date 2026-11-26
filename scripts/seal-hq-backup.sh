#!/usr/bin/env bash
# Seal the Google service-account key + the list of HQ sheets for the nightly lab backup.
# Usage: scripts/seal-hq-backup.sh ~/Downloads/sa.json ~/hq-sheets.txt
#   hq-sheets.txt: one "Name|spreadsheetId" per line (keep this file OUT of git).
set -euo pipefail
sa="${1:?service-account json}"; list="${2:?hq-sheets.txt}"
out="apps/hq-backup/overlays/dev/sealedsecret.yaml"
kubectl create secret generic hq-backup-secrets -n dev \
  --from-file=sa.json="$sa" --from-file=HQ_SHEETS="$list" --dry-run=client -o yaml \
  | kubeseal --controller-name sealed-secrets-controller --controller-namespace kube-system -o yaml > "$out"
echo "Wrote $out"
echo "Share each sheet (Viewer) with: $(python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["client_email"])' "$sa")"
echo "Then: git add $out && git commit -m 'lab: hq-backup secret' && git push"
