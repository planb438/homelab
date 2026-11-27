# Changelog

Newest first. One line per change that affects what runs or how to use it. Update `docs/lab-guide.md` in the same PR.

| Date | Change | Where |
| --- | --- | --- |
| 2026-11-27 | Security: encryption at rest (secretbox) + API audit log with auto-undo, kube-bench before/after report, Velero-on-S3 bootstrap script | ansible/security.yml, scripts/ |
| 2026-11-27 | Admin portals: ACB field-service admin, Ask Canada / Ask Authority community Q&A (new aa.dev.lab.local), CloudKanata tenant ops panel with RBAC + admission guard; two-step login for admins | apps/sitekit, apps/site-* |
| 2026-11-26 | Lab guide added to the repo; PR checklist + docs reminder workflow | docs/, .github/ |
| 2026-11-26 | Nightly HQ Google Sheets backup (setup pending: service account) | apps/hq-backup |
| 2026-11-26 | ParkingClub lab copy at pc.dev.lab.local (real Worker in workerd, test Stripe only, no email) | apps/parkingclub-lab |
| 2026-11-26 | Lab copies follow each site repo's `dev` branch; CI tags images by commit and Argo CD rolls out | apps/site-*, .github/workflows |
| 2026-11-26 | Fix: sealed secrets double name prefix (ck-ck-…) | apps/site-*/overlays/dev |
| 2026-11-26 | sitekit + 4 lab site copies with logins and PostgreSQL (ck, ask, acb, hub .dev.lab.local) | apps/sitekit, apps/site-* (PR #2) |
| 2026-11-20 | ParkingClub demo (static nginx) at parkingclub.lab.local | apps/parkingclub |
| 2026-11-19 | Civic Hub (Ask Canada) collector, web, Postgres, Grafana | apps/civic-hub |
| 2026-11-18 | Cluster builds end-to-end; Argo CD UI via Traefik | infra/, ansible/, clusters/ |
