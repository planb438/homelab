# Platform components — what, why, how it's set, and the AWS equivalent

**Last updated: 2026-11-18** · Owner: Adari Bain (CloudKanata) · Live versions: `bash scripts/versions.sh`

This page is written to be handed to a client. Every component below is installed from Git — nothing is
clicked together by hand — so the same design can be rebuilt on a laptop, on EC2, or on EKS.

## Layers at a glance
| Layer | Lab (this repo) | Production on AWS |
|---|---|---|
| Machines | KVM/libvirt VMs, made by Terraform | EC2 (kubeadm) or **EKS** managed nodes, made by Terraform |
| OS config + Kubernetes | Ansible → kubeadm | Same Ansible on EC2 · managed by AWS on EKS |
| Pod network + NetworkPolicy | Calico | Calico or VPC CNI with network policy |
| Delivery | **Argo CD** (GitOps, app-of-apps) | Same |
| Load balancer IPs | MetalLB (L2) | AWS NLB / AWS Load Balancer Controller |
| Ingress | Traefik | Same (behind NLB) or ALB |
| TLS | cert-manager + private lab CA | cert-manager + Let's Encrypt (Route 53 DNS-01) |
| Storage | local-path-provisioner | EBS CSI (`gp3`) |
| Secrets in Git | Sealed Secrets | External Secrets + AWS Secrets Manager (or Sealed Secrets) |
| Policy | Kyverno + Pod Security Admission | Same |
| Metrics | metrics-server | Same (+ Prometheus/Grafana or CloudWatch) |

---

## KVM / libvirt  ·  `infra/libvirt/`
**What:** Linux's built-in hypervisor; runs the three node VMs (cp1, w1, w2) on the desktop.
**Why:** real multi-node Kubernetes (like production) on one machine; VM snapshots let a broken CKS lab be undone in seconds; no cloud bill.
**Why not the alternatives:** VirtualBox (slower, no Terraform-grade automation), kind/minikube (containers, not real nodes — can't practise kubelet/etcd/node hardening), MicroK8s on the host (mixes lab and desktop).
**Settings:** NAT network 192.168.122.0/24 · DHCP shrunk to .100–.199 · nodes .10–.12 · `security_driver = "none"` (Ubuntu 26.04 AppArmor fix).
**AWS:** replaced by EC2 instances or EKS node groups (`infra/aws`).

## Terraform  ·  `infra/libvirt/`
**What:** declares the VMs, disks and cloud-init. **Why:** the same tool builds the AWS VPC/EC2/EKS later, so the skill and the review process carry over.
**Settings:** provider `dmacvicar/libvirt ~> 0.8.1` · Ubuntu 24.04 (noble) cloud image · cp1 2 vCPU/3 GB/30 GB, workers 2 vCPU/4 GB/60 GB.
**AWS:** `hashicorp/aws` provider + S3/DynamoDB remote state.

## Ansible + kubeadm  ·  `ansible/`
**What:** prepares every node (swap off, kernel modules, containerd with systemd cgroups, pinned kube packages) and runs `kubeadm init/join`.
**Why kubeadm:** it's what CKA/CKS and most self-managed production clusters use; rebuild in ~10 minutes. "Kubernetes the hard way" stays a one-off learning exercise.
**Settings:** `k8s_minor: v1.34` · `pod_cidr: 192.168.0.0/16` · kubeconfig written to `ansible/kubeconfig-lab`.
**AWS:** same playbook works on EC2 (Ubuntu); on EKS this layer disappears.

## Calico  ·  installed by Ansible
**What:** pod network (CNI). **Why:** enforces **NetworkPolicy** — required for zero-trust and every CKS network lab (Flannel ignores policies).
**Settings:** `calico_version: v3.30.3`.
**AWS:** on EC2 use VXLAN mode (or disable source/dest check); on EKS use VPC CNI with network policy enabled, or Calico.

## Argo CD  ·  `scripts/bootstrap-argocd.sh`, `clusters/lab/`
**What:** GitOps controller — makes the cluster match this repo and undoes manual drift.
**Why:** every change is a reviewed Git commit (audit trail, rollback = revert); the same repo can drive several clusters (lab → EKS).
**Settings:** app-of-apps `clusters/lab/root.yaml` · ordered by sync waves · ApplicationSets for `apps/*/overlays/*` (dev/stage/prod) and `labs/*` · UI at https://argocd.lab.local via Traefik TLS passthrough.
**Production notes:** change the admin password, then SSO (Dex/GitHub); AppProjects per team; no `kubectl apply` by hand.

## local-path-provisioner  ·  `platform/local-path/`
**What:** default StorageClass that creates volumes on the node's disk.
**Why:** without a default StorageClass every PVC stays *Pending* — the "storage error" from earlier builds.
**Settings:** v0.0.31 · marked default.
**Limits:** data lives on one node. **AWS:** EBS CSI driver, `gp3` default StorageClass.

## MetalLB  ·  `clusters/lab/apps/01-02`, `platform/metallb-config/`
**What:** gives `type: LoadBalancer` services a real IP on a bare-metal/VM network.
**Why:** so Traefik gets one stable address (like a cloud load balancer) instead of NodePorts.
**Settings:** L2 mode · pool 192.168.122.240–250.
**AWS:** not used — AWS NLB/ALB does this.

## Traefik  ·  `clusters/lab/apps/03-traefik.yaml`
**What:** ingress controller — one entry point routing by hostname, terminating TLS.
**Why Traefik:** ingress-nginx is retired; Traefik is maintained, light, supports standard Ingress + Gateway API + TCP/TLS passthrough.
**Settings:** chart 42.4.1 · `service.spec.type: LoadBalancer` · default IngressClass `traefik`.
**AWS:** same chart behind an NLB, or AWS Load Balancer Controller (ALB).

## cert-manager  ·  `clusters/lab/apps/04`, `platform/cert-issuers/`
**What:** issues and renews TLS certificates automatically.
**Why:** no hand-made or expired certs; one annotation on an Ingress gets a cert.
**Settings:** CRDs via chart · ClusterIssuer `lab-ca` (private CA `homelab-ca`, ECDSA P-256).
**AWS:** ClusterIssuer `letsencrypt-prod` with Route 53 DNS-01 (IRSA). Ingress manifests don't change.

## metrics-server  ·  `clusters/lab/apps/05`
**What:** CPU/memory metrics for `kubectl top` and HorizontalPodAutoscaler.
**Settings:** `--kubelet-insecure-tls` (lab only: kubelet certs are self-signed). **Production:** enable kubelet serving-cert approval and drop the flag.

## Kyverno  ·  `clusters/lab/apps/06-07`, `policies/kyverno/`, `labs/*/policy.yaml`
**What:** policy engine — validates, mutates and reports on resources, written as YAML.
**Why Kyverno (not OPA Gatekeeper):** policies are plain Kubernetes YAML (no Rego), easier for client teams to read and own.
**Settings:** cluster policies in **Audit** (require requests/limits, no privileged) for dev/stage/prod; labs use namespaced `Policy` in **Enforce**.
**Path to production:** Audit → fix reports → Enforce, one policy at a time.

## Pod Security Admission  ·  namespace labels
**What:** Kubernetes' built-in pod hardening levels. **Settings:** lab namespaces `enforce: restricted`. **AWS:** identical.

## Sealed Secrets  ·  `clusters/lab/apps/09-sealed-secrets.yaml`
**What:** encrypts Secrets with the cluster's public key so they can be committed safely.
**Why:** old repos committed plaintext passwords; this removes that risk without needing a cloud vault.
**Settings:** chart 2.22.0 · controller `sealed-secrets-controller` in `kube-system` · kubeseal 0.41.2 on the desktop.
**Must do:** back up the sealing key outside Git. **AWS:** External Secrets Operator + Secrets Manager.

## Prometheus + Grafana (kube-prometheus-stack)  ·  `clusters/lab/optional/13-monitoring.yaml`
**What:** metrics for every node, pod and app, dashboards, alerts. **Why:** you can't run prod without seeing it; same stack most clients run.
**Settings:** chart 93.4.1 · 7-day retention on a 10 Gi volume · ~1 GB RAM · control-plane scrapers off (kubeadm binds them to localhost) · Grafana admin via SealedSecret · https://grafana.lab.local.
**AWS:** same chart on EKS, or Amazon Managed Prometheus/Grafana.

## Velero  ·  `clusters/lab/apps/14-velero.yaml` (on since 2026-11-27)
**What:** backs up Kubernetes objects **and volume data** to S3; restores namespaces or the whole cluster.
**Why:** Git rebuilds the apps; only a backup brings back the data. Backups live **off** the cluster (S3), so losing the laptop doesn't lose them.
**Settings:** chart 12.2.5 (Velero 1.18) · AWS plugin 1.14.4 · file-system backup (node agent, kopia) because local-path can't snapshot · nightly 2:30 AM, kept 30 days · IAM user limited to one bucket · keys sealed · bucket `cloudkanata-homelab-backups` (ca-central-1) · databases dumped by pre-backup hooks (local-path disks are hostPath, which Velero skips) until the lab moves to NFS · node agent also on cp1.
**AWS:** same; on EKS use IRSA instead of keys and EBS snapshots.

## Falco  ·  `clusters/lab/apps/15-falco.yaml` (on since 2026-11-28)
**What:** runtime security. A DaemonSet on all 3 nodes reads every container's system calls through **modern eBPF** and raises an alert when a rule matches: a shell opened in a pod, a write under `/etc`, a read of `/etc/shadow`, a package manager run in a container, an unexpected outbound connection.
**Why:** Kyverno and Pod Security stop bad pods from *starting*; Falco catches bad behaviour in pods that are *already running* (a CKS exam domain). It is the camera; Kyverno is the door lock.
**Settings:** chart 9.2.2 (Falco 0.45.2) · `driver.kind: modern_ebpf` (no kernel module to build) · JSON alerts, priority Notice and above · 128 Mi request / 512 Mi limit per node (chart default 512 Mi request is too much for cp1) · official rules pulled at start, no hourly auto-update (Git decides) · Falcosidekick off (turn on to send alerts to Slack, email or Grafana) · namespace `falco` labelled Pod Security `privileged`.
**Use:** `kubectl -n falco logs ds/falco -f` · test: `bash scripts/falco-test.sh`.
**AWS:** same chart on EKS EC2 nodes (not Fargate); or GuardDuty EKS Runtime Monitoring.

---

## Change log
| Date | Change |
|---|---|
| 2026-11-19 | Monitoring + Velero added (optional, enable with scripts) |
| 2026-11-18 | Document created; Sealed Secrets and lab CA added; labs 01–06 |
