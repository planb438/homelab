#!/usr/bin/env bash
# Copy the HQ backups from the lab to ./hq-backups on this computer.   Usage: scripts/hq-backup-get.sh
set -euo pipefail
kubectl -n dev apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata: {name: hq-backup-reader, labels: {app.kubernetes.io/name: hq-backup}}
spec:
  securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: r
      image: busybox:1.37
      command: ["sleep", "600"]
      resources: {requests: {cpu: 10m, memory: 16Mi}, limits: {memory: 32Mi}}
      securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      volumeMounts: [{name: b, mountPath: /backups, readOnly: true}]
  volumes: [{name: b, persistentVolumeClaim: {claimName: hq-backups}}]
EOF
kubectl -n dev wait --for=condition=Ready pod/hq-backup-reader --timeout=120s
kubectl -n dev cp hq-backup-reader:/backups ./hq-backups
kubectl -n dev delete pod hq-backup-reader --wait=false
ls -R ./hq-backups | tail -20
