# Civic Hub — Ask Canada (v0.1.0)

**Last updated: 2026-11-19** · Built by CloudKanata · First country: Canada (AskBahamas and schools next, same engine)

Tracks official Government of Canada data, records **what changed and when**, keeps full history,
and shows it on a public page + Grafana. Every source is an official open-data endpoint (no scraping).

```
CronJob collector (every 6 h; 2 h in dev)          Deployment web (FastAPI)      Grafana (read-only DB user)
  IRCC processing times (by country + in Canada)  ─┐   /            what changed     ops + trend dashboards
  Canada.ca News Centre API                        ├─► PostgreSQL ◄─ /api/changes
  Statistics Canada WDS (CPI, unemployment, pop.)  │   items · changes · observations · runs
  Bank of Canada Valet (policy rate, USD/CAD)      │
  open.canada.ca (recently updated datasets)      ─┘
```

| Table | Holds |
|---|---|
| `items` | latest value of every tracked item (≈2,000 rows for Canada) |
| `changes` | every new / changed / removed event → the public "what changed" feed |
| `observations` | value history → Grafana trend charts (IRCC days, CPI, rates…) |
| `runs` | one row per source per collector run → health panel; failed sources don't stop the others |

The **first** run of each source is a baseline (stored, not announced), so the feed starts filling from the second run.

## URLs (lab)
| | dev | prod |
|---|---|---|
| Public page | https://askcanada.dev.lab.local | https://askcanada.lab.local |
| Grafana | https://grafana-askcanada.dev.lab.local | https://grafana-askcanada.lab.local |
| API docs | `/api/docs` | `/api/docs` |

Add these hosts to the `/etc/hosts` line with your Traefik IP.

## Turn it on (once per environment)
```bash
git pull
bash scripts/seal-civic-hub.sh dev          # needs kubeseal (labs/03). Prints the Grafana admin password ONCE.
git add apps/civic-hub/overlays/dev && git commit -m "civic-hub: dev secrets" && git push
# first data now instead of waiting for the schedule:
kubectl -n dev create job --from=cronjob/civic-hub-collector civic-hub-first-run
kubectl -n dev logs -f job/civic-hub-first-run
```
Then the same with `prod`.

**One-time GitHub step:** the image is published to `ghcr.io/planb438/civic-hub` by the
`civic-hub-image` workflow. GitHub makes new packages **private** — open
github.com/planb438?tab=packages → civic-hub → Package settings → Change visibility → **Public**
(the code is public already; this lets the cluster pull without a password).

## Release flow
dev runs `:edge` (rebuilt on every change to `app/`). When dev looks right:
`git tag civic-hub-v0.2.0 && git push --tags` → CI builds `:0.2.0` → set `newTag: 0.2.0` in `overlays/prod` → merge.

## Security
Non-root, read-only filesystem, all capabilities dropped, no service-account token · DB reachable only from the hub's
own pods (NetworkPolicy) · Grafana uses a SELECT-only DB user · passwords only as SealedSecrets · resource limits on everything.

## Add a source / a country
Write a `fetch_*()` in `app/civic_hub/sources.py` that returns `Item`s, add a `Source(...)` with its country code, done —
change tracking, history, page and Grafana pick it up. AskBahamas = `country="bs"` sources + a second CronJob with `--country bs`.

## Run locally
```bash
cd apps/civic-hub/app && pip install -r requirements.txt pytest && python -m pytest -q tests
DATABASE_URL=sqlite:///hub.db python -m civic_hub.collect --country ca
DATABASE_URL=sqlite:///hub.db uvicorn civic_hub.web:app --port 8080
```

## Data licence
Contains information licensed under the Open Government Licence – Canada; Bank of Canada data per its terms of use.
Not an official Government of Canada site — the page says so and links every item to its source.
