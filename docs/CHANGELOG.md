# Changelog

Newest first. One line per change that affects what runs or how to use it. Update `docs/lab-guide.md` in the same PR.

| Date | Change | Where |
| --- | --- | --- |
| 2026-11-26 | Lab guide added to the repo; PR checklist + docs reminder workflow | docs/, .github/ |
| 2026-11-26 | Nightly HQ Google Sheets backup (setup pending: service account) | apps/hq-backup |
| 2026-11-26 | ParkingClub lab copy at pc.dev.lab.local (real Worker in workerd, test Stripe only, no email) | apps/parkingclub-lab |
| 2026-11-26 | Lab copies follow each site repo's `dev` branch; CI tags images by commit and Argo CD rolls out | apps/site-*, .github/workflows |
| 2026-11-26 | Fix: sealed secrets double name prefix (ck-ck-…) | apps/site-*/overlays/dev |
| 2026-11-26 | sitekit + 4 lab site copies with logins and PostgreSQL (ck, ask, acb, hub .dev.lab.local) | apps/sitekit, apps/site-* (PR #2) |
| 2026-11-20 | ParkingClub demo (static nginx) at parkingclub.lab.local | apps/parkingclub |
| 2026-11-19 | Civic Hub (Ask Canada) collector, web, Postgres, Grafana | apps/civic-hub |
| 2026-11-18 | Cluster builds end-to-end; Argo CD UI via Traefik | infra/, ansible/, clusters/ |
