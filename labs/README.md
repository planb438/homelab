# Labs — old ideas, rebuilt the production way

**Last updated: 2026-11-18**

Each folder is one lab. Argo CD deploys it into its own namespace (`lab-<folder>`) through
`clusters/lab/apps/12-labs.yaml`. Every lab has: a README (old way → new way → why → AWS equivalent),
the manifests Argo CD applies, and `tests/test.sh` that prints PASS/FAIL. "Bad" examples live in `tests/`
and are only ever sent with `kubectl apply --dry-run=server`, so nothing insecure is ever created.

| Lab | Replaces (old repo) | Proves | Needs |
|---|---|---|---|
| [01-pod-security](01-pod-security/) | CKS-Walk-Thru 04/05 | no root, no privilege escalation, no host access, read-only FS | built in (PSA) |
| [02-network-policy](02-network-policy/) | Network-Policy-Learning-Environment, 06 | default deny, DNS-only egress, one allowed path | Calico |
| [03-sealed-secrets](03-sealed-secrets/) | plain Secrets in argocd-applications-homelab | passwords in Git only encrypted | Sealed Secrets + kubeseal |
| [04-ingress-tls](04-ingress-tls/) | NodePort services everywhere | ClusterIP + Traefik + TLS from lab CA; NodePort refused | Traefik, cert-manager, Kyverno |
| [05-rbac-least-privilege](05-rbac-least-privilege/) | velero cluster-admin, 12/13 SA abuse | one-object Role, no auto-mounted tokens | built in |
| [06-supply-chain](06-supply-chain/) | 07 private registry, 08 cosign, disallow-latest | no `:latest`, registry allow-list, digest audit | Kyverno |

Run them all: `for t in labs/*/tests/test.sh; do echo "== $t"; bash "$t"; done`

## Next labs (planned, in this order)
| Lab | From old repo | Notes |
|---|---|---|
| 07-encryption-at-rest | CKS 03, aws-k8s-lab 002 | **Done 2026-11-27** in `ansible/security.yml` (secretbox) |
| 08-audit-logging | CKS 09, aws-k8s-lab 001 | **Done 2026-11-27** in `ansible/security.yml`; ship logs later |
| 09-falco-runtime | CKS 10 | **Done 2026-11-28** as platform app `clusters/lab/apps/15-falco.yaml`; test with `scripts/falco-test.sh` |
| 10-backups | minio-velero-gitops, aws-k8s-lab disaster-recovery | **Done 2026-11-27**: Velero to AWS S3 (no MinIO); etcd snapshot CronJob still to do |
| 11-signed-images | CKS 08, 11 SBOM | cosign sign + Kyverno `verifyImages`; Syft/Grype in CI |
| 12-runtime-sandbox | mock tasks 08/09 | gVisor RuntimeClass, AppArmor profiles |
| 13-monitoring | prometheus-grafana-gitops | kube-prometheus-stack in prod only (RAM) |

Apps from `argocd-applications-homelab` (odoo, wiki.js, snipe-it, wordpress, dolibarr, nextcloud, erpnext)
move to `apps/<name>/` one at a time using labs 03 + 04 + 05 as the pattern — see `docs/migrating-apps.md`.

Backups of the old repos: git tag `backup-2026-11-18` in each repo + zips in Google Drive (CloudKanata) → `🧪 Homelab/Repo backups – 2026-11-18`.
