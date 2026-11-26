# sitekit — lab copies of the sites, with logins and a database

Lab only. Nothing here touches the live sites (GitHub Pages / Cloudflare stay exactly as they are).

Each pod:
- **git-sync** pulls the site's public repo every 5 minutes → the real pages are served at `/` (same files as live).
- **sitekit** (FastAPI) adds a private area at `/app`: log in, invite-only sign-up, roles (admin / staff / client),
  forms saved to PostgreSQL, a staff inbox, user admin, password change, audit log.
- **PostgreSQL 17** (one per site, its own volume). Only the app pod can reach it (NetworkPolicy).

| Lab app | Host | Pulls from | Forms |
|---|---|---|---|
| site-cloudkanata | https://ck.dev.lab.local | cloudkanata-site | contact |
| site-askcanada | https://ask.dev.lab.local | ask-canada | question |
| site-acb | https://acb.dev.lab.local | acb-landscaping | quote |
| site-hub | https://hub.dev.lab.local | planb438.github.io | (private launcher for admins) |

## First run (per site)
```bash
./scripts/seal-sitekit.sh cloudkanata dev you@example.com   # prints the admin password once
./scripts/seal-sitekit.sh askcanada  dev you@example.com
./scripts/seal-sitekit.sh acb        dev you@example.com
./scripts/seal-sitekit.sh hub        dev you@example.com  launcher.json   # optional private links
git add apps/site-*/overlays/dev/sealedsecret.yaml && git commit -m "lab: sitekit secrets" && git push
```
Add the hosts to `/etc/hosts` (your Traefik IP), open `https://<host>/app`, log in, then use **Users → Invite** to make more logins.

`launcher.json` example: `[{"group":"Business","title":"ParkingClub HQ","url":"https://docs.google.com/…","note":"sheet"}]`

## Develop locally
```bash
cd apps/sitekit/app && pip install -r requirements.txt pytest && pytest -q
SITE_ROOT=../../../.. ADMIN_EMAIL=a@b.c ADMIN_PASSWORD=change-me-12 SECURE_COOKIES=false uvicorn sitekit.main:app --reload
```
SQLite is used when `DATABASE_URL` isn't set; in the cluster it's PostgreSQL.
