# Lab copies of the sites (dev namespace)

Lab only. The live sites (GitHub Pages, Cloudflare, Stripe live) are never touched by anything here.

| Lab app | Address | Follows | What it adds |
|---|---|---|---|
| site-cloudkanata | https://ck.dev.lab.local | cloudkanata-site @ **dev** | logins, contact form → PostgreSQL |
| site-askcanada | https://ask.dev.lab.local | ask-canada @ **dev** | logins, question form → PostgreSQL |
| site-acb | https://acb.dev.lab.local | acb-landscaping @ **dev** | logins, quote form → PostgreSQL |
| site-hub | https://hub.dev.lab.local | planb438.github.io @ **dev** | private launcher (admins) |
| parkingclub-lab | https://pc.dev.lab.local | parkingclub-site @ **dev** (private, read-only deploy key) | the real Worker in workerd, local KV, no emails, Stripe **test** only |
| hq-backup | (nightly job) | your HQ Google Sheets | .xlsx copy of every HQ sheet, kept 30 days |

## How changes flow
- **Site pages:** push to the site repo's `dev` branch → the lab copy updates within ~5 min (ParkingClub ~2 min).
  Happy? Merge `dev` → `main` → it goes live. Keep dev current after other changes to main:
  `git checkout dev && git merge main && git push`.
- **sitekit / pc-lab runner code:** push to `main` here → CI tests, builds an image tagged with the commit,
  commits the new tag into the overlays → Argo CD rolls it out. Run `git pull` before your next push.
- **Kubernetes settings:** edit `apps/*/overlays/dev` → Argo CD applies it.

## One-time setup
- Sites: `scripts/seal-sitekit.sh <cloudkanata|askcanada|acb|hub> dev <email>` (done).
- ParkingClub: `scripts/seal-parkingclub-lab.sh` → adds a read-only deploy key, prints your first admin invite.
- HQ sheets: make a Google Cloud service account (no roles needed), download its JSON key, share each sheet with its
  email as **Viewer**, then `scripts/seal-hq-backup.sh sa.json hq-sheets.txt` (`Name|sheetId` per line; keep it out of git).
  Run once now: `kubectl -n dev create job --from=cronjob/hq-backup hq-backup-now`. Copy files home: `scripts/hq-backup-get.sh`.
- GitHub Packages: make **sitekit** and **pc-lab-runner** public (or add a pull secret).
- /etc/hosts: add `pc.dev.lab.local` next to the others.

## Lost a sitekit password
Never changed it: `kubectl get secret ck-sitekit-secrets -n dev -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d`
Changed it: set a new hash —
```bash
read -s -p "New password: " PW; echo
HASH=$(kubectl exec -n dev deploy/ck-sitekit-web -c web -- python -c "from sitekit.security import hash_password as h; print(h('$PW'))")
kubectl exec -n dev ck-sitekit-db-0 -- psql -U sitekit -d sitekit -c "UPDATE users SET pw_hash='$HASH', active=true WHERE email='you@email';"
```

## Develop sitekit locally
```bash
cd apps/sitekit/app && pip install -r requirements.txt pytest && python -m pytest -q
SITE_ROOT=/path/to/a/site ADMIN_EMAIL=a@b.c ADMIN_PASSWORD=change-me-12 SECURE_COOKIES=false uvicorn sitekit.main:app --reload
```
