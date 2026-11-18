# homelab — lab → dev / stage / prod with GitOps

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
# 0. host prep (once) — KVM, libvirt pool, DHCP range, Ansible collections, SSH key
scripts/host-prep.sh            # then log out/in; install Terraform: https://developer.hashicorp.com/terraform/install

# 1. VMs
cd infra/libvirt && terraform init && terraform apply      # needs ~/.ssh/id_ed25519.pub

# 2. Kubernetes
cd ../../ansible && ansible-playbook -i inventory/lab.ini site.yml
export KUBECONFIG=$PWD/kubeconfig-lab

# 3. GitOps
../scripts/bootstrap-argocd.sh
```

## Day to day
| Command | What it does |
|---|---|
| `scripts/lab.sh snapshot clean` | snapshot all 3 VMs |
| `scripts/lab.sh revert clean` | roll back after a CKS lab |
| `scripts/lab.sh stop` / `start` | give the RAM back to your desktop |
| PR to `main` | CI validates Terraform + every overlay; merge = Argo CD deploys |

## Promotion flow
`apps/<app>/base` is shared. Overlays only change what differs (replicas, resources, image tag, host).
Change `dev` → PR → merge → check → copy the same change to `stage`, then `prod`.

## Moving to AWS later
See `docs/aws.md`. Keep `apps/` and `policies/` as they are; add `clusters/eks` and `infra/aws`
(reuse your `EKS-Terraform-Lab` modules: VPC, EKS, IRSA, EBS CSI).

## Related repos
* `argocd-applications-homelab` — app manifests to migrate into `apps/` one by one
* `Kubernetes-CKS-Security-Labs`, `CKS-Security-Labs-Preparation` — security labs to run on this cluster
* `EKS-Terraform-Lab` — course notes / Terraform modules for the AWS phase

**No secrets in this repo.** Use SOPS + age or Sealed Secrets when an app needs one.
