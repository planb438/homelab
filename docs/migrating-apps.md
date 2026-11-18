# Moving apps from `argocd-applications-homelab`

For each app (wiki-js, nextcloud, odoo, erp-next, snipeit, dolibarr, wordpress, postgres, prometheus-grafana, minio-velero, falco):

1. `apps/<app>/base/` — copy the manifests (or a Helm-based kustomization). Remove any `storageClassName:` so the
   cluster default is used (local-path here, gp3 on EKS). Add CPU/memory requests and a memory limit.
2. `apps/<app>/overlays/dev|stage|prod/` — only the differences: replicas, resources, image tag, ingress host.
3. Open a PR → CI renders every overlay → merge → Argo CD creates `<app>-dev`, `<app>-stage`, `<app>-prod`.

**RAM budget (11 GB cluster):** platform ≈ 2 GB. Heavy apps — ERPNext (~2–3 GB), Odoo (~1 GB + Postgres),
Nextcloud (~1 GB + DB), Prometheus stack (~1.5 GB) — can't all run in three environments. Suggested:
heavy apps get a `prod` overlay only (or `dev` with `replicas: 0` until needed); light apps (wiki-js, podinfo,
snipeit) can run everywhere. Delete an overlay folder and Argo CD removes that environment.

**Secrets:** never commit them. Add SOPS + age (or Sealed Secrets) the first time an app needs a password.
