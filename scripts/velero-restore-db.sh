#!/usr/bin/env bash
# After `velero restore`, load the data saved by the pre-backup hooks back into the apps.
#   bash scripts/velero-restore-db.sh dev            # every database + ParkingClub lab in "dev"
#   bash scripts/velero-restore-db.sh dev acb-sitekit-db-0
# Why: local-path disks can't be copied by Velero, so each backup carries a dump in an emptyDir called "backup".
set -euo pipefail
NS="${1:?usage: velero-restore-db.sh <namespace> [pod]}"; ONLY="${2:-}"
pods="$ONLY"
[ -z "$pods" ] && pods="$(kubectl -n "$NS" get pods -o name | sed 's|pod/||' | grep -E -- '-db-0$|^pc-lab-' || true)"
[ -z "$pods" ] && { echo "No database pods in $NS"; exit 0; }
for p in $pods; do
  if [[ "$p" == pc-lab-* ]]; then
    echo "== $p: ParkingClub KV"
    kubectl -n "$NS" exec "$p" -c worker -- sh -c 'test -s /backup/data.tgz && tar -xzf /backup/data.tgz -C /data' \
      && kubectl -n "$NS" delete pod "$p" --wait=false && echo "   restored (pod restarting)" || echo "   no dump found, skipped"
  else
    echo "== $p: PostgreSQL"
    kubectl -n "$NS" wait --for=condition=Ready "pod/$p" --timeout=180s >/dev/null
    kubectl -n "$NS" exec "$p" -c postgres -- sh -c \
      'test -s /backup/db.dump && pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --no-owner /backup/db.dump' \
      && echo "   restored" || echo "   no dump found (or restore warnings above)"
  fi
done
