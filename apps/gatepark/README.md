# GatePark (demo)

Clickable demo of GatePark, a YYZ airport parking booking site. One static page, sample data only.

| Where | URL |
|---|---|
| Lab (Argo CD, namespace `prod`) | https://gatepark.lab.local |
| Public copy (GitHub Pages) | https://planb438.github.io/gatepark-demo/ |

How it runs: the page lives in `base/site/index.html`. Kustomize turns it into a ConfigMap (with a hash
in the name), and an unprivileged nginx serves it read-only. Edit the page, push, and Argo CD rolls the pod.

Access: add `gatepark.lab.local` to `/etc/hosts` pointing at the Traefik IP (same line as the other `*.lab.local` names).

Keep the public copy in sync: copy `base/site/index.html` to `index.html` in planb438/gatepark-demo.

Next (phase 1): real backend (FastAPI + Postgres like civic-hub), lot dashboard for check-in staff, Stripe later.
