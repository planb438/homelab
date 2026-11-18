# homelab — lab → dev / stage / prod with GitOps

**Last updated: 2026-11-18** · Status: cluster builds end-to-end on Ubuntu 26.04 (tested by Adari, Nov 18 2026)

One laptop, one Kubernetes cluster in VMs, three environments, everything rebuilt from this repo.
Built so the **same app manifests move to AWS EKS later** — only the cluster layer changes.

```
Host (Ubuntu desktop, i5-8265U 4c/8t, 18 GB RAM)
└── KVM/libvirt  (Terraform: infra/libvirt)
    ├── cp1      2 vCPU · 3 GB   192.168.122.10   control plane
    ├── w1       2 vCPU · 4 GB   192.168.122.11   worker
    └── w2       2 vCPU · 4 GB   192.168.122.12   worker
        └── kubeadm cluster (Ansible: ansible/)  + Calico (NetworkPolicy for CKS labs)
            └── Argo CD (clusters/lab) ── watches this repo
                ├── platform: local-path storage (default StorageClass), MetalLB, Traefik,
                │             cert-manager, metrics-server, Kyverno (+ policies/ in Audit mode)
                └── apps/<app>/overlays/{dev,stage,prod} → namespaces dev / stage / prod
```

## Why this shape
* **Host stays a desktop.** Nodes are VMs: snapshot before you break something, revert in seconds.
* **11 GB for the cluster, ~7 GB left for the desktop.** Heavy apps (ERPNext, Odoo, Nextcloud,
  Prometheus stack) do not all fit at once — run them in `prod`, keep `dev`/`stage` light, scale to 0 when idle.
* **"Storage errors" fix:** PVCs stayed *Pending* before because there was no **default StorageClass**.
  `platform/local-path` installs one, so every app's PVC binds. On EKS this becomes `gp3` (EBS CSI).
* **kubeadm, not Kubernetes-the-hard-way, for daily use** — it is what CKA/CKS use and rebuilds in ~10 min.
  Do the hard way once on a branch for learning.

## Quick start
```bash
# 0. host prep (once, as YOUR user — not root): KVM, libvirt, AppArmor fix, Terraform, Ansible, SSH key
bash scripts/host-prep.sh
# >>> log out and back in (or reboot) so the libvirt group applies, then check:
groups | grep libvirt && virsh -c qemu:///system list --all

# 1. VMs
cd infra/libvirt && terraform init && terraform apply      # needs ~/.ssh/id_ed25519.pub

# 2. Kubernetes
cd ../../ansible && ansible-playbook site.yml
cd .. && export KUBECONFIG=$PWD/ansible/kubeconfig-lab   # add this line to ~/.bashrc
kubectl get nodes

# 3. GitOps
bash scripts/bootstrap-argocd.sh
```

## Day to day
| Command | What it does |
|---|---|
| `scripts/lab.sh snapshot clean` | snapshot all 3 VMs |
| `scripts/lab.sh revert clean` | roll back after a CKS lab |
| `scripts/lab.sh stop` / `start` | give the RAM back to your desktop |
| `bash scripts/reset-lab.sh` | delete the 3 VMs + disks and start over |
| PR to `main` | CI validates Terraform + every overlay; merge = Argo CD deploys |

## Promotion flow
`apps/<app>/base` is shared. Overlays only change what differs (replicas, resources, image tag, host).
Change `dev` → PR → merge → check → copy the same change to `stage`, then `prod`.

## Opening Argo CD and the apps (through Traefik)
Traefik gets an IP from MetalLB. Point the lab names at it once:
```bash
IP=$(kubectl -n traefik get svc traefik -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
echo "$IP argocd.lab.local podinfo.dev.lab.local podinfo.stage.lab.local podinfo.prod.lab.local" | sudo tee -a /etc/hosts
```
- Argo CD: https://argocd.lab.local (user `admin`; self-signed cert, so accept the browser warning)
- Apps: http://podinfo.dev.lab.local, `.stage.`, `.prod.`
- Fallback if Traefik is down: `kubectl -n argocd port-forward svc/argocd-server 8080:443` → https://localhost:8080

Argo CD is routed with an `IngressRouteTCP` in TLS passthrough (`platform/argocd-ingress/`), so Argo CD needs no config change.
New app = add an `Ingress` with `ingressClassName: traefik` and a host, then add that host to `/etc/hosts`.

## Moving to AWS later
See `docs/aws.md`. Keep `apps/` and `policies/` as they are; add `clusters/eks` and `infra/aws`
(reuse your `EKS-Terraform-Lab` modules: VPC, EKS, IRSA, EBS CSI).

## Related repos
* `argocd-applications-homelab` — app manifests to migrate into `apps/` one by one
* `Kubernetes-CKS-Security-Labs`, `CKS-Security-Labs-Preparation` — security labs to run on this cluster
* `EKS-Terraform-Lab` — course notes / Terraform modules for the AWS phase

**No secrets in this repo.** Use SOPS + age or Sealed Secrets when an app needs one.

## Troubleshooting (Ubuntu 26.04)
| Error | Fix |
|---|---|
| `scripts/...: Permission denied` | run with `bash scripts/<name>.sh`, as your user (not `sudo bash`) |
| `Package 'qemu-kvm' has no installation candidate` | fixed in host-prep (installs `qemu-system-x86`) |
| `kubectl: command not found` | `sudo snap install kubectl --classic --channel=1.34/stable` (host-prep now does this) |
| `libvirt-sock: permission denied` | log out/in after host-prep; `newgrp libvirt` works for one terminal |
| `NO_PUBKEY FC9CA96ACA026560` (Terraform) | key must come from `https://apt.releases.hashicorp.com/gpg` — host-prep does this |
| podinfo `CreateContainerConfigError` | image user is non-numeric; fixed by `runAsUser: 100` in `apps/podinfo/base` |
| `traefik` namespace empty / no ingress IP | `kubectl -n argocd get applications`, then `kubectl -n argocd describe application traefik`; chart is now pinned to 42.4.1 |
| `Could not open ...ubuntu-noble-base.qcow2: Permission denied` | AppArmor; host-prep sets `security_driver = "none"` in `/etc/libvirt/qemu.conf` and restarts libvirt |

## What you install vs. what Argo CD installs
You only run **three things by hand**: `host-prep.sh` → `terraform apply` → `ansible-playbook site.yml`,
then `bootstrap-argocd.sh` once. From that point **Argo CD installs everything else from this repo**:

| Installed automatically (in order) | Why |
|---|---|
| local-path storage (default StorageClass) | PVCs bind instead of staying *Pending* |
| MetalLB (192.168.122.240-250) | `LoadBalancer` services get an IP |
| Traefik | ingress / HTTP routing |
| cert-manager | TLS certificates |
| metrics-server | `kubectl top`, autoscaling |
| Kyverno + `policies/` (Audit) | guardrails: resources set, no privileged pods |
| every `apps/<app>/overlays/<env>` | your apps in `dev`, `stage`, `prod` |

Never `kubectl apply` apps by hand — change Git, and Argo CD makes the cluster match (it also undoes manual edits).

## How to deploy an app
```bash
git checkout -b add-wikijs
mkdir -p apps/wikijs/base apps/wikijs/overlays/{dev,prod}
# base/: Deployment, Service, PVC (no storageClassName), resources requests + memory limit
# overlays/<env>/kustomization.yaml: resources: [../../base] + what differs (replicas, host, image tag)
kubectl kustomize apps/wikijs/overlays/dev          # check it renders
git add apps/wikijs && git commit -m "wikijs: base + dev/prod" && git push -u origin add-wikijs
# open a PR → CI must pass → merge to main
```
Within ~3 minutes Argo CD creates **wikijs-dev** and **wikijs-prod** (namespaces `dev`, `prod`). Watch it:
`kubectl get applications -n argocd` or the UI (`kubectl -n argocd port-forward svc/argocd-server 8080:443`).

**Promote** dev → prod: make the same change in `overlays/prod` in a second PR.
**Remove** an environment: delete its overlay folder and merge — Argo CD deletes it from the cluster.
**Copy the pattern** from `apps/podinfo/`. Bring apps over from `argocd-applications-homelab` one at a time (`docs/migrating-apps.md`).

## Is this production-ready?
**The workflow is production-grade; this hardware is not.** It is the right place for dev, stage, demos,
CKS labs and your own low-stakes tools. Do not put clients' data here yet.

| Production-grade already | Gap on this laptop | Fix (in order) |
|---|---|---|
| GitOps: every change reviewed, versioned, reversible | 1 control plane — if cp1 dies, the cluster can't be managed | 3 control planes, or EKS (managed control plane) |
| CI validates every PR | local-path storage: data lives on one worker; lose w1 = lose its volumes | Velero + MinIO backups **copied off the laptop**; later Longhorn or EBS (gp3) |
| Policies (Kyverno), NetworkPolicy (Calico) | 11 GB RAM, laptop CPU, home power & internet | a VPS or EKS for real prod |
| Rebuild from scratch in ~20 min | private NAT network — not reachable from the internet | Cloudflare Tunnel for safe public access |
| Snapshots / reset scripts | no monitoring or alerts yet | Prometheus + Grafana + alerting (prod overlay only) |

**Rule of thumb:** if losing the data for a day would hurt a client, it belongs on EKS or a VPS with backups —
and thanks to this repo, moving it there is a new `clusters/eks` folder, not a rewrite (`docs/aws.md`).

## Changelog
| Date | Change |
|---|---|
| 2026-11-18 (pm) | Argo CD UI at https://argocd.lab.local via Traefik (TLS passthrough); podinfo UID fix; Traefik chart pinned to 42.4.1 |
| 2026-11-18 | Fresh-install fixes for Ubuntu 26.04 (qemu-system-x86, AppArmor, Terraform repo, kubectl on host); `reset-lab.sh`; bootstrap finds the kubeconfig itself; deploy guide + production-readiness notes |
| 2026-11-17 | Initial repo: libvirt VMs (Terraform), kubeadm (Ansible), Argo CD app-of-apps, dev/stage/prod overlays, Kyverno, CI |
