# Optional platform apps (not deployed until you enable them)

Argo CD only watches `clusters/lab/apps/`. Apps here need a secret first, so a script seals the
secret **and** copies the app into `apps/` in one step:

| App | Enable with | Needs |
|---|---|---|
| `13-monitoring.yaml` (Prometheus + Grafana) | `bash scripts/setup-monitoring.sh` | kubeseal |
| `14-velero.yaml` (nightly backups to S3) | `bash scripts/setup-velero.sh <bucket> <region>` | S3 bucket + IAM user (`docs/aws-velero.md`) |
