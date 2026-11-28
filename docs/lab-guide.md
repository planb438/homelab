# Your Home Lab, Explained — from libvirt to the lab sites

> Living guide to this repo. **Update it in the same pull request as any change to `apps/`, `platform/`, `clusters/` or `infra/`**, and add a line to [CHANGELOG.md](CHANGELOG.md).
> Last reviewed: 2026-11-26 (admin portals added)

## The big picture

Your lab is a small copy of how real companies run Kubernetes. It is one desktop running three virtual machines that form one Kubernetes cluster, and that cluster is managed entirely from one Git repo (planb438/homelab). You never click to deploy: you change the repo, and the cluster makes itself match it.

It is built in five layers. Each one sits on the one below it, and each was built by a different tool:

| Layer | What it is | Built by | In your repo |
| --- | --- | --- | --- |
| 1. Machines | 3 VMs on your desktop (cp1, w1, w2) | Terraform + libvirt | infra/libvirt/ |
| 2. Kubernetes | The cluster itself, joined across the 3 VMs | Ansible + kubeadm | ansible/ |
| 3. Platform | Shared services every app uses: web entry, certificates, storage, secrets, rules | Argo CD | clusters/lab/, platform/, policies/ |
| 4. GitOps | The rule that turns every folder under apps/ into a running app | Argo CD ApplicationSet | clusters/lab/apps/10-workloads.yaml |
| 5. Apps | Civic Hub, the lab site copies, ParkingClub lab, HQ backup, podinfo | Kustomize files + container images | apps/ |

```
 5 · Apps        Civic Hub · site copies · ParkingClub lab · HQ backup · podinfo
 4 · GitOps      Argo CD: apps/<app>/overlays/<env> → dev/stage/prod  ◄── GitHub repo + Actions (CI)
 3 · Platform    Traefik · MetalLB · cert-manager (lab-ca) · Sealed Secrets · Kyverno · storage
 2 · Kubernetes  kubeadm 1.34 · containerd · Calico · built by Ansible
 1 · Machines    cp1 3 GB · w1 4 GB · w2 4 GB on KVM/libvirt · built by Terraform
```

Only layer 4 talks to GitHub: Argo CD pulls from the repo, so nothing outside your desktop ever pushes into the cluster.

**Why build it this way?** Three reasons, and they are the same reasons a client pays for this kind of setup:

1. **Rebuildable.** Everything is code. If a VM dies, you run the same commands and get the same lab back in about 10 minutes.
2. **Reviewable.** Every change is a Git commit, so you can see who changed what, when, and undo it.
3. **Portable.** Only layers 1 and 2 are tied to your desktop. Layers 3 to 5 move to AWS EKS later almost unchanged.

**How a change travels, in one line:** you push to GitHub → GitHub Actions tests and builds (for app code) → Argo CD notices the repo changed → it applies the change to the cluster → Traefik sends your browser to the new version.

## Layer 1 — Machines: KVM, libvirt and Terraform

Your desktop (Intel i5-8265U, 4 cores, 18 GB RAM) runs three virtual machines. Together they use 11 GB, which leaves about 7 GB for you to keep using the desktop.

| VM | Role | CPU | RAM | Disk | IP address |
| --- | --- | --- | --- | --- | --- |
| cp1 | Control plane (the cluster's brain) | 2 | 3 GB | 30 GB | 192.168.122.10 |
| w1 | Worker (runs your apps) | 2 | 4 GB | 60 GB | 192.168.122.11 |
| w2 | Worker (runs your apps) | 2 | 4 GB | 60 GB | 192.168.122.12 |

### The pieces and what each does

- **KVM** is built into the Linux kernel. It lets your CPU run other operating systems at near-full speed. It is the actual engine.
- **QEMU** pretends to be the hardware of each VM: disk, network card, screen.
- **libvirt** is the manager on top. It starts, stops and snapshots VMs and runs the private network they share. `virsh` is its command line.
- **Terraform** describes the VMs in a file and creates them to match. You say "I want 3 VMs with these sizes" and `terraform apply` makes it so. Running it twice changes nothing; that property is called *idempotent*.
- **cloud-init** runs inside each VM on its first boot. It sets the hostname, creates the `ubuntu` user, installs your SSH key, turns off password login and installs the guest agent.

### Step by step: what `scripts/host-prep.sh` then `terraform apply` do

1. **Install the host tools:** QEMU, libvirt, Ansible and Terraform.
2. **Add you to the libvirt and kvm groups,** so you can manage VMs without sudo. This is why you must log out and back in once.
3. **Set `security_driver = "none"` in libvirt.** Ubuntu's AppArmor blocked QEMU from opening the shared base disk Terraform creates. This is a lab-only shortcut; a production host would write an AppArmor rule instead.
4. **Create the storage pool** (/var/lib/libvirt/images) and **start the `default` network.**
5. **Shrink the network's DHCP range to .100–.199.** That keeps .10–.12 free for the fixed node addresses and .240–.250 free for MetalLB (layer 3). Without this, two things could get the same address.
6. **Terraform downloads one Ubuntu 24.04 cloud image** and uses it as a shared, read-only base disk.
7. **It gives each VM its own disk layered on that base** (copy-on-write). Each VM only stores what it changes, so three VMs cost far less space than three full installs.
8. **It builds a small cloud-init disk per VM** holding the hostname, your SSH key and the fixed IP address.
9. **It creates the three VMs** with `host-passthrough` CPU (the VM sees your real CPU, which is faster) and `autostart = false` (they don't start when the desktop boots).

### The network

libvirt's `default` network is a private network inside your desktop: 192.168.122.0/24, with your desktop at .1 acting as the router. The VMs reach the internet through your desktop (NAT), but nothing outside your desktop can reach them. That is why only your desktop can open the lab sites, and why your `/etc/hosts` line points at 192.168.122.240.

### Why VMs, not kind or minikube?

kind and minikube fake a cluster inside containers on one machine. Real VMs give you real separate nodes, so you can practise things the CKA and CKS exams test: draining a node, a worker going down, network rules between machines. They also take **snapshots**: `scripts/lab.sh snapshot before-upgrade` saves all three VMs, and `scripts/lab.sh revert before-upgrade` puts them back in seconds.

**Client version:** "The servers are defined in code, so we can rebuild them identically at any time and roll back in seconds."

**AWS equivalent:** Terraform with the AWS provider creating EC2 instances, or EKS node groups.

## Layer 2 — Building Kubernetes: Ansible and kubeadm

One command, `ansible-playbook site.yml`, turns three plain Ubuntu VMs into a working Kubernetes 1.34 cluster.

- **Ansible** logs into each VM over SSH and runs a list of tasks, in order, on the right machines. Like Terraform, running it again only changes what is missing. The inventory file (`ansible/inventory/lab.ini`) says which VM is the control plane and which are workers.
- **kubeadm** is the official Kubernetes installer, and the one the CKA and CKS exams use. It creates the control plane and joins workers.

### Step by step: what the playbook does

**On all three VMs (the `common` role):**

1. **Wait for cloud-init to finish,** so nothing collides with first-boot setup.
2. **Turn swap off,** now and at boot. The kubelet refuses to run with swap, because it needs to know exactly how much memory is really free.
3. **Load two kernel modules:** `overlay` (lets container images stack in layers) and `br_netfilter` (lets the firewall see traffic between pods).
4. **Set three network switches (sysctl)** so the node forwards traffic between pods and other nodes.
5. **Install containerd,** the container runtime that actually starts and stops containers.
6. **Set containerd to use systemd cgroups,** so it and the kubelet agree on how CPU and memory are limited. A mismatch here causes random restarts.
7. **Add the official Kubernetes package repo for v1.34** and install `kubelet`, `kubeadm` and `kubectl`.
8. **Hold those three packages,** so a routine `apt upgrade` can't upgrade Kubernetes by surprise. Cluster upgrades are a planned job.

**On cp1 only (the `control_plane` role):**

1. **`kubeadm init`** creates the control plane: the API server (the front door every command goes through), etcd (the database holding the cluster's state), the scheduler (decides which node runs each pod) and the controller manager (keeps reality matching what was asked for). The pod address range is set to 192.168.0.0/16.
2. **Copy the admin kubeconfig** to the ubuntu user.
3. **Install Calico,** the network plugin (CNI). It gives every pod an IP address and lets pods on different nodes talk. You chose Calico because it enforces **NetworkPolicies**, the firewall rules your apps rely on. Some simpler plugins ignore them.
4. **Create a join command** with a fresh token for the workers.
5. **Copy the kubeconfig to your desktop** as `ansible/kubeconfig-lab`. That file is your key to the cluster: `kubectl` uses it.

**On w1 and w2 (the `worker` role):** run the join command. Each worker's kubelet registers with the API server and starts taking pods.

### What runs where afterwards

| Part | Runs on | What it does |
| --- | --- | --- |
| API server, etcd, scheduler, controller manager | cp1 | The brain: stores and decides |
| kubelet | all 3 | The agent on each node: starts pods and reports back |
| containerd | all 3 | Runs the containers |
| kube-proxy | all 3 | Routes Service addresses to the right pods |
| Calico | all 3 | Pod networking and NetworkPolicy |
| Your apps | w1, w2 | cp1 is kept for the control plane |

**Client version:** "The cluster is installed by script with the official tools, so every rebuild is identical and takes about 10 minutes."

**AWS equivalent:** EKS gives you the control plane as a managed service; you no longer run cp1 yourself.

## Layer 3 — Platform services: the shared toolbox

A bare cluster can run containers but can't give them web addresses, certificates, disks or secrets. The platform layer adds those, once, for every app. You installed only Argo CD by hand (`scripts/bootstrap-argocd.sh`). Argo CD then installed everything else from the repo.

### How the platform gets installed: "app of apps"

1. **`bootstrap-argocd.sh`** installs Argo CD into the `argocd` namespace, then applies one file: `clusters/lab/root.yaml`.
2. **`root.yaml` is an Argo CD Application named `root-lab`.** Its only job is to watch the folder `clusters/lab/apps/`.
3. **Each file in that folder is itself an Application** (local-path, MetalLB, Traefik, and so on). So the root app creates the other apps, and each of those installs one tool. This pattern is called *app of apps*.
4. **Sync waves set the order.** Each Application has a number; Argo CD finishes lower numbers first. Storage and networking go in wave −3, then the tools in wave −1, then their settings in waves 0 and 1, then your apps in waves 1 and 2. Order matters because a setting can't be applied before the tool that understands it exists.
5. **`automated: prune + selfHeal`** on every app. *Self-heal* means if someone changes the cluster by hand, Argo CD puts it back to what Git says. *Prune* means if you delete a file from Git, Argo CD deletes that thing from the cluster.

### Each platform service and its purpose

| # | Service | Problem it solves | How you use it |
| --- | --- | --- | --- |
| 00 | **local-path storage** | Apps asking for a disk (a PVC) stayed stuck at *Pending* because nothing could provide one | It's the default StorageClass: any PVC gets a folder on the node's disk. Your Postgres databases use it |
| 01–02 | **MetalLB** | On a cloud, a `LoadBalancer` Service gets a public IP automatically; on your desktop nothing hands one out | It gives LoadBalancer Services an address from 192.168.122.240–250. Traefik got .240 |
| 03 | **Traefik** | You need one front door that sends each web address to the right app | It's the ingress controller. Every `Ingress` file you write (host name → Service) becomes a Traefik route |
| 04 + 11 | **cert-manager + lab-ca** | Browsers want HTTPS, but public certificate authorities can't verify a private `.lab.local` name | cert-manager created your own certificate authority, **homelab-ca** (10-year, lab only). Any Ingress with `cert-manager.io/cluster-issuer: lab-ca` gets a certificate automatically. You trusted the CA once on your desktop |
| 05 | **metrics-server** | You want to see CPU and memory use | Powers `kubectl top pods` and `kubectl top nodes` |
| 06 + 07 | **Kyverno + policies** | Nothing stops someone deploying an unsafe container | Rules checked on every pod in dev, stage and prod: no privileged containers, and every container must set CPU and memory requests and limits. They run in **Audit** mode: breaking a rule is reported, not blocked |
| 08 | **Argo CD ingress** | Opening the Argo CD screen needed a port-forward | Publishes it at https://argocd.lab.local through Traefik |
| 09 | **Sealed Secrets** | Passwords can't go into a public Git repo, but GitOps needs everything in Git | The controller in `kube-system` holds a private key. `kubeseal` on your desktop encrypts a Secret with the matching public key. The encrypted *SealedSecret* is safe to commit; only your cluster can turn it back into a Secret |
| 10 | **workloads ApplicationSet** | Writing one Argo CD Application per app per environment is repetitive | Turns every `apps/<app>/overlays/<env>` folder into an app (Layer 4) |
| 12 | **labs ApplicationSet** | Your CKS practice labs need the same automation | Turns every `labs/NN-name` folder into its own namespace (6 labs: pod security, network policy, sealed secrets, ingress TLS, RBAC, supply chain) |
| optional | **Prometheus + Grafana, Velero** | Monitoring and off-site backups | Off by default to save RAM. Turn on with `scripts/setup-monitoring.sh` or `scripts/setup-velero.sh` |

### How a browser request reaches an app

1. You type https://ck.dev.lab.local. Your `/etc/hosts` says that name is 192.168.122.240.
2. That address belongs to Traefik's LoadBalancer Service, announced by **MetalLB**.
3. **Traefik** shows the certificate cert-manager made for that name, then reads the host name and finds the matching Ingress.
4. The Ingress points to a **Service** (a stable internal name, such as `ck-sitekit-web`).
5. The Service forwards to whichever **pod** is healthy, on w1 or w2.

**Client version:** "Every app gets HTTPS, a web address, storage and encrypted secrets automatically, and safety rules are checked on everything that runs."

**AWS equivalent:** MetalLB becomes an AWS load balancer, local-path becomes EBS gp3 disks, lab-ca becomes Let's Encrypt. Traefik, cert-manager, Kyverno, Sealed Secrets and Argo CD stay as they are.

## Layer 4 — GitOps: how a folder becomes a running app

GitOps means **Git is the single source of truth**: the cluster runs exactly what the repo describes. To add an app, you add a folder. To remove one, you delete the folder.

### The one rule that does it: the `workloads` ApplicationSet

An ApplicationSet is a template that makes Argo CD Applications for you. Yours (`clusters/lab/apps/10-workloads.yaml`) says:

1. **Look in the repo for every folder matching `apps/*/overlays/*`.**
2. **For each one, make an Application** named `<app>-<env>`. For example, `apps/site-acb/overlays/dev` becomes `site-acb-dev`.
3. **Deploy it into the namespace named after the folder:** `dev`, `stage` or `prod`. `CreateNamespace=true` creates it if missing.
4. **Keep it synced automatically,** with prune and self-heal on (Layer 3).

That's why you never write an Argo CD Application for an app: making the folder is enough. It's also why the `sitekit/base` folder isn't deployed on its own. It has no `overlays` folder, so the rule doesn't match it.

### Kustomize: base and overlays

Every app is written in two parts, so you never copy and paste YAML:

- **base** = the parts that are the same everywhere (the Deployment, Service, database).
- **overlay** = the small changes for one environment or one site (a host name, an image tag, a setting). The overlay's `kustomization.yaml` points at the base and lists the changes.

Kustomize merges them when Argo CD syncs. The main tools you'll see in an overlay:

| Kustomize field | What it does | Example in your repo |
| --- | --- | --- |
| `resources` | Which files and bases to include | `../../../sitekit/base`, `ingress.yaml`, `sealedsecret.yaml` |
| `namePrefix` | Adds a prefix to every name, so 4 copies can share a namespace | `ck-` turns `sitekit-web` into `ck-sitekit-web` |
| `labels` | Adds a label to everything, including selectors | `app.kubernetes.io/part-of: site-acb` keeps each site's network rules separate |
| `configMapGenerator` | Builds a ConfigMap of settings | the site name, colour, Git repo, branch, forms |
| `images` | Swaps the image tag | `newTag: <commit>`, which CI updates |
| `patches` | Precise edits to the base | pointing each site at its own secret |

### Environments: dev, stage, prod

They are three namespaces on the same cluster, not three clusters. A namespace is a walled-off area: its own names, its own network rules, its own limits.

| Namespace | Meant for | What's there now |
| --- | --- | --- |
| dev | Newest code; things may break | Civic Hub (dev), the 4 site copies, ParkingClub lab, HQ backup, podinfo |
| stage | A final check before prod | podinfo |
| prod | The stable version | Civic Hub (prod), the old ParkingClub demo, podinfo |

To promote an app you add an overlay for the next environment, usually with a pinned image tag instead of the newest.

**Client version:** "Nobody deploys by hand. Every change is a reviewed Git commit, the cluster applies it within minutes, and rolling back is reverting the commit."

**AWS equivalent:** identical. This layer doesn't care where the cluster is.

## Layer 5 — The apps that were already there

| App | Address | Namespaces | Pattern it shows |
| --- | --- | --- | --- |
| podinfo | podinfo.dev / .stage / .prod .lab.local | dev, stage, prod | The same app in three environments from one base |
| ParkingClub demo | parkingclub.lab.local | prod | The simplest app: a static page on unprivileged nginx |
| Civic Hub (Ask Canada) | askcanada.dev.lab.local + grafana-askcanada.dev.lab.local | dev, prod | A real app: your own code, a database, a scheduled job, a dashboard |

### Civic Hub, the template for everything since

Civic Hub collects official Government of Canada updates and tracks how they change. It's the pattern the lab sites copied:

- **Your own image,** `ghcr.io/planb438/civic-hub`, built by GitHub Actions from `apps/civic-hub/app`.
- **A collector CronJob** that runs the image on a schedule (every 6 hours, every 2 hours in dev) and writes to the database.
- **A web Deployment** that shows the results, with a health check at `/healthz`.
- **PostgreSQL 17 as a StatefulSet.** A StatefulSet is for things with data: each pod keeps the same name and the same disk across restarts.
- **Grafana** with a ready-made Ask Canada dashboard.
- **NetworkPolicies:** only the app may reach the database, and only Traefik may reach the app.
- **A SealedSecret** for the database password, made by `scripts/seal-civic-hub.sh`.
- **Hardened pods:** non-root user (10001), read-only filesystem, no extra Linux capabilities, default seccomp profile.

### The building blocks, in plain words

| Object | What it is | Why it exists |
| --- | --- | --- |
| Pod | One or more containers that run together | The smallest thing Kubernetes runs |
| Deployment | Keeps N copies of a pod running; replaces them on updates | For apps that keep no data inside the pod |
| StatefulSet | Like a Deployment, but each pod keeps its name and disk | For databases |
| Service | A stable name and address in front of changing pods | Pods come and go; the Service name stays |
| Ingress | A rule: this host name → that Service | How Traefik knows where to send traffic |
| ConfigMap | Plain settings | Change settings without rebuilding the image |
| Secret / SealedSecret | Passwords and keys | Kept out of images and out of plain Git |
| PersistentVolumeClaim | A request for a disk | Data survives pod restarts |
| NetworkPolicy | A firewall rule between pods | Limits who can talk to what |
| CronJob | A pod that runs on a schedule | Collectors, backups |

## The lab site copies (sitekit)

Lab versions of your sites with usernames, passwords and databases, with the live sites left alone. One reusable app, **sitekit**, deployed once per site.

| Lab address | Copy of | Pulls pages from | Extra form |
| --- | --- | --- | --- |
| ck.dev.lab.local | CloudKanata | cloudkanata-site, dev branch | contact |
| ask.dev.lab.local | Ask Canada | ask-canada, dev branch | question |
| acb.dev.lab.local | ACB Landscaping | acb-landscaping, dev branch | quote |
| hub.dev.lab.local | Your Hub | planb438.github.io, dev branch | private launcher for admins |
| aa.dev.lab.local | Ask Authority | askauthority, dev branch | community Q&A (Canada, Bahamas, USA) |

### What sitekit is

A small Python web app (FastAPI) in `apps/sitekit/app`. It does two jobs:

1. **Serves your real site files at `/`,** exactly as GitHub Pages does. Paths starting with `/.git` are blocked.
2. **Adds a private area at `/app`:**
   - log in and out; passwords stored as PBKDF2 hashes (210,000 rounds), never as plain text
   - lockout after 6 wrong passwords in 15 minutes
   - roles: admin, staff, client
   - invite-only sign-up: an admin makes a one-time link that lasts 7 days
   - forms saved to PostgreSQL, with a hidden spam trap
   - a staff inbox to set each message's status and add notes
   - a users page to invite and disable people, and a page to change your password
   - an audit log of logins and changes
   - CSRF tokens on every form, so another site can't submit forms as you

### Every piece of one site copy, and why

Take CloudKanata. Kustomize adds `ck-` to every name.

| Object | Name | Purpose |
| --- | --- | --- |
| SealedSecret → Secret | ck-sitekit-secrets | Database password, session signing key, admin email and password |
| ConfigMap | ck-sitekit-config-… | Site name, colour, Git repo, branch (`dev`), database host, form fields |
| StatefulSet + headless Service | ck-sitekit-db | PostgreSQL 17 with its own 1 GB disk |
| Deployment | ck-sitekit-web | 1 pod, 3 containers (below) |
| Service | ck-sitekit-web | Stable address for Traefik |
| Ingress | ck-sitekit | ck.dev.lab.local → the Service, with a lab-ca certificate |
| NetworkPolicy | ck-sitekit-db | Only this site's web pod may open the database (port 5432) |
| NetworkPolicy | ck-sitekit-web | Only Traefik may reach the web pod (port 8080) |

**Inside the web pod**, the three containers share one folder:

1. **git-sync-init** runs once at start. It downloads the site repo's `dev` branch, so the pages exist before the app starts.
2. **web** is sitekit itself. It serves the files and the `/app` area, and connects to Postgres.
3. **git-sync** keeps running and pulls new commits every 5 minutes, so page edits appear without a rebuild.

**Security settings on every container:** non-root user, read-only filesystem, no privilege escalation, all Linux capabilities dropped, and memory requests and limits set so Kyverno is satisfied.

### How it was first deployed (Nov 25–26, 2026)

1. **Built and tested sitekit.** Committed it to a separate branch, `lab-sites`, so nothing reached the cluster until you chose.
2. **First image build failed.** The test runner couldn't find the code folder. Fixed with `tests/conftest.py`.
3. **`scripts/seal-sitekit.sh` run 4 times.** Each run made random passwords and keys, encrypted them with the cluster's public key, wrote a `sealedsecret.yaml`, and showed the admin password once.
4. **PR #2 merged into main.** The ApplicationSet saw four new `overlays/dev` folders and created four Argo CD apps. Before the merge Traefik answered `404 page not found`: it had no Ingress for those names yet.
5. **Bug: pods stuck at `CreateContainerConfigError`.** The secret files were named `ck-sitekit-secrets`, and Kustomize added `ck-` again (`ck-ck-sitekit-secrets`). Sealed secrets are locked to their exact name, so the controller couldn't unlock it. Fix: name it `sitekit-secrets` in the file and let Kustomize add the prefix once.
6. **All 8 pods Running** (4 web, 4 database) and logins work on all four.

### If you lose a password

The admin account is created only once, the first time the database is empty, so re-sealing never overwrites it.

- **Never changed it?** `kubectl get secret ck-sitekit-secrets -n dev -o jsonpath='{.data.ADMIN_PASSWORD}' | base64 -d`
- **Changed it?** Make a new hash with sitekit and write it into the `users` table with `psql`. The exact commands are in `apps/sitekit/README.md`.

## Admin portals (sitekit modules)

Each lab site now has an admin portal that fits its business. They are modules of sitekit, switched on per site with `MODULES=` in the site's overlay, so they share one login system, one security model and one test suite.

| Site | Module | Address | Who uses it |
| --- | --- | --- | --- |
| ACB Landscaping | `acb` | https://acb.dev.lab.local/acb | You and office staff (everything), crew (their jobs only, no prices), clients (their quotes and invoices) |
| Ask Canada | `qa` | https://ask.dev.lab.local/qa | Public reads; members sign up to ask, answer and vote; staff give Official answers and moderate |
| Ask Authority (Canada, Bahamas, USA) | `qa` | https://aa.dev.lab.local/qa | Same as Ask Canada, with country categories |
| CloudKanata | `ops` | https://ck.dev.lab.local/ops | Admins act on tenants; staff can look but not change |

### Shared by every portal

- **Two-step login (TOTP).** Admins must set it up on first login (`/app/account/2fa`) with Google Authenticator, Microsoft Authenticator, 1Password or Authy. Codes follow RFC 6238; no extra service or RAM needed. Other roles can turn it on too.
- **Roles per site,** invite links for staff and crew, open sign-up only where it makes sense (the Q&A sites).
- **CSRF tokens, rate limits, spam traps and an audit log** on every form, as before.

### ACB Landscaping — field-service admin (`mod_acb.py`)

| Area | What it does |
| --- | --- |
| Clients & properties | Address, area (from the postal code), lot size, gate code, pets, site instructions |
| Lead pipeline | lead → quoted → active → past; one click imports website quote requests as leads |
| Service catalog | Preset prices (mowing, cleanups, mulch, hedges, snow and salting) used by quotes |
| Quotes | Line items + 13% HST; a private link lets the client approve (typed name) or decline online; approval creates the job |
| Scheduling | Weekly view grouped by area with a one-tap Google Maps route per day; recurring visits (weekly, bi-weekly, monthly) create the next visit when one is done; "rain day" shifts a day's jobs to the next working day |
| Crew | "My jobs" for the next 7 days, directions, gate code, clock in/out (with location if the phone allows), before/after photos, mark done. Crew never see prices or billing |
| Invoices | Month-end "invoice completed jobs", sent/paid status, overdue detection, a client link, CSV export for QuickBooks or Xero |
| Messages | Tomorrow's reminders and thank-you + Google review requests as ready-to-send texts and emails (the lab sends nothing itself) |
| Dashboard | Recurring revenue, unpaid and overdue totals, quote conversion, jobs today/this week, estimated vs actual hours |

Photos are stored in the site's database (6 MB limit each). Job photos only, never people.

### Ask Authority — community Q&A (`mod_qa.py`)

Ideas taken from Question2Answer (last release 2022) and rebuilt for this stack:

- Questions with categories and tags, answers, up/down votes, **best answer** chosen by the asker.
- **Official answers:** staff answers become Official only with an https link to an approved government domain (canada.ca, gc.ca, gov.bs, usa.gov…), which keeps the brand's "point to official sources" rule.
- **Points and levels** (Newcomer → Member → Helper → Expert → Authority) and a top-contributors page.
- **Moderation:** posts from members under 10 points wait for approval; three flags hide a post until staff review it.
- Search, related questions by tag, view counts, a `/qa/sitemap.xml` for search engines, plain text only (no HTML from users), link limits for new members.

### CloudKanata — operations panel (`mod_ops.py`)

A thin, safe wrapper around the Kubernetes API for your own projects and the clients you add:

1. **Tenant directory:** each tenant gets a namespace `t-<id>` with a plan (small, medium or large).
2. **What "create" applies:** a ResourceQuota (CPU, memory, storage, pods, no LoadBalancers or NodePorts), default container limits, a NetworkPolicy that only lets Traefik and the tenant's own pods in, and the Pod Security **restricted** level.
3. **Lifecycle buttons:** change plan, suspend (scale to zero and remember replicas), resume, quarantine (cut all traffic in and out), release, soft delete (suspended + isolated, purge only after 14 days), restore, purge, reconcile.
4. **Guardrails:** destructive actions need the tenant id typed exactly; refusals are logged too. Every action is written to an append-only log you can export as JSON.
5. **Support view:** read-only pods, restarts, quota use and recent warnings for a tenant, no password needed.
6. **Billing stays outside:** a signed webhook (`/ops/hooks/billing`, HMAC with `OPS_WEBHOOK_SECRET`) sets a billing flag from Stripe or Invoice Ninja; you decide whether to suspend.
7. **Nodes are read-only:** the panel shows health and the exact drain/uncordon commands; draining stays a deliberate command you run.

**How the cluster limits the panel (defense in depth):**

- Its ServiceAccount (`ck-sitekit-ops`) can touch namespaces, quotas, limits, NetworkPolicies and deployment replica counts, and nothing else: no Secrets, no pod exec, no RBAC.
- A **ValidatingAdmissionPolicy** (`ck-sitekit-ops-tenants-only`) makes the API server refuse any change by that account outside namespaces named `t-*` with the `cloudkanata.io/tenant` label. Even a bug in the app can't touch `dev`, `argocd` or `kube-system`.
- Tenant namespaces are created by the panel, not by Git, so Argo CD doesn't manage or prune them.

## ParkingClub lab copy and the HQ Sheets backup

### ParkingClub lab (pc.dev.lab.local)

The live parkingclub.ca is a **Cloudflare Worker**: JavaScript on Cloudflare's servers, with KV storage for bookings and logins, Stripe for payments and Cloudflare email for alerts. The lab runs the *same code* in **workerd**, the open-source engine Cloudflare itself uses, through `wrangler dev`.

1. **git-sync-init** downloads the `dev` branch of the **private** parkingclub-site repo with a **read-only deploy key** (an SSH key that opens one repo only and can't push).
2. **worker** runs `start.sh`, which:
   1. refuses to start if given a **live** Stripe key, so no real charge can happen in the lab;
   2. copies the code to a writable folder;
   3. writes a lab-only config (`labconfig.mjs`) that removes the parkingclub.ca domains, removes email sending, and makes links show https://pc.dev.lab.local;
   4. on the very first start, creates the one-time admin invite in the lab's own KV;
   5. runs the Worker and reloads it whenever git-sync brings a new commit.
3. **git-sync** pulls new commits every 2 minutes.

Its data lives in a 1 GB volume, `pc-lab-data`, separate from Cloudflare's KV. The Deployment uses `Recreate`, so only one copy ever writes to it.

| Live parkingclub.ca | Lab pc.dev.lab.local |
| --- | --- |
| Code from `main` | Code from `dev` |
| Cloudflare KV | Local KV on a lab volume |
| Emails the ParkingClub inbox | Sends no email |
| Stripe live key | Stripe test key only, or none |
| Real admin accounts | Separate lab accounts |

The `pc-lab-runner` image is smoke-tested in GitHub Actions before every release: it must serve pages, seed the invite, make https links and refuse a live key.

### HQ Sheets backup (nightly)

The `hq-backup` CronJob runs at 3:23 AM cluster time, which is UTC (10:23 PM Toronto). It logs into Google as a read-only **service account** and saves each HQ sheet as .xlsx, all tabs, into the `hq-backups` volume, one folder per day, kept 30 days. It never writes to Google. Setup: service account key + sheets shared as Viewer + `scripts/seal-hq-backup.sh`. Copy files home with `scripts/hq-backup-get.sh`.

## Security hardening and backups

Three things a client asks about first, and how the lab does them.

### 1. Encryption at rest (Secrets in etcd)

By default Kubernetes stores Secrets in etcd as plain base64: anyone with a copy of etcd or its backups can read every password. `ansible/security.yml` turns on the API server's **EncryptionConfiguration** with the `secretbox` provider (XSalsa20-Poly1305):

1. A random 32-byte key is created **on cp1** (`/etc/kubernetes/enc/encryption-config.yaml`, mode 600). It is never in Git; a copy goes to `~/homelab-keys/` on your desktop for restores.
2. An etcd snapshot is taken, then the API server manifest is patched (flag + mount). The original manifest is backed up to `/root/apiserver-backups/` — never inside `/etc/kubernetes/manifests`, where a copy would start a second API server.
3. If the API server isn't healthy within 3 minutes, the playbook **puts the old manifest back** and stops.
4. Every existing Secret is re-written so it gets encrypted too.
5. Proof: the playbook reads a Secret straight from etcd and checks it starts with `k8s:enc:secretbox:v1:key1`.

Keep `~/homelab-keys/encryption-config.yaml` safe and backed up: without it an etcd backup can't be restored. Velero backups are not affected (Velero reads through the API).

### 2. API audit log

Every request to the API server is recorded in `/var/log/kubernetes/audit/audit.log` on cp1 (CIS values: kept 30 days, 10 files of 100 MB). The policy (`ansible/roles/apiserver_hardening/files/audit-policy.yaml`):

| What | Level | Why |
| --- | --- | --- |
| Health checks, kube-proxy watches, events, leases | not logged | noise |
| Secrets, ConfigMaps, tokens | metadata only | who touched them, never the values |
| RBAC changes | full request and response | privilege changes are the first thing to investigate |
| exec / attach / port-forward | request | who got a shell into a pod |
| Any other create, update, patch, delete | request | what changed |
| Everything else (reads) | metadata | who looked |

Read it: `ssh ubuntu@192.168.122.10 sudo tail -f /var/log/kubernetes/audit/audit.log | jq -c '{user: .user.username, verb, uri: .requestURI}'`

### 3. kube-bench (CIS Kubernetes Benchmark)

kube-bench checks each node against the CIS benchmark. The playbook installs the latest release on all three nodes and runs it **before and after** hardening, then writes `reports/kube-bench/<date>/SUMMARY.md` on your desktop: PASS/FAIL/WARN per node, what this run fixed, and the remaining FAILs with the fix for each. Reports stay on your desktop (`reports/` is git-ignored) because they list weaknesses.

Run it:

```bash
cd ansible
ansible-playbook security.yml                    # before report -> encryption + audit -> after report
ansible-playbook security.yml -e snapshot=true   # also snapshot the 3 VMs first (slower)
ansible-playbook security.yml --tags bench       # just a fresh report
```

Fresh builds get all of this automatically: `site.yml` now ends by running `security.yml`.

**First report (Nov 27, 2026):** cp1 65 pass / 11 fail, w1 and w2 15 pass / 2 fail. Fixed in the next pass: profiling off on the API server, controller manager and scheduler; CIS audit retention; manifest and kubelet file permissions. Known exceptions, documented on purpose:

| Check | Why it stays | Plan |
| --- | --- | --- |
| 1.1.12 etcd data dir owned by etcd:etcd | kubeadm runs etcd as root, so an `etcd` user owns nothing | Accept (same on most kubeadm clusters) |
| 1.2.5 --kubelet-certificate-authority | Needs kubelet serving certificates signed by the cluster CA (`serverTLSBootstrap` + CSR approval) | Next pass |
| 4.2.6 protectKernelDefaults | The kubelet refuses to start unless several kernel settings match exactly | Next pass, with the sysctls set first |

### 4. Velero backups to AWS S3

Velero copies every namespace (objects and volume data) to S3 every night at 2:30 AM Toronto and keeps 30 days. One command sets everything up with the AWS CLI:

```bash
bash scripts/aws-velero-bootstrap.sh cloudkanata-homelab-backups ca-central-1
git add -A && git commit -m "velero: on" && git push
```

It creates a **private, encrypted, versioned** bucket, an IAM user `velero-homelab` that can only use that bucket, and a new access key that goes straight into a SealedSecret: never printed or saved in plain text. Then it switches the Velero app on for Argo CD. Test with `velero backup create first-test --wait` and a restore into a scratch namespace (`docs/aws-velero.md`).

Note: Velero backups contain your Secrets as the API returns them (decrypted), which is why the bucket is private and encrypted, and the IAM user is limited to it.

**Why the databases need an extra step.** The lab's storage (local-path) creates each disk as a `hostPath` folder on a node, and Velero's file copy skips those. The first full backup (`first-test`) saved all 1,029 objects but skipped every database disk. So each database pod (sitekit-db, civic-hub-db) and the ParkingClub lab carry a **pre-backup hook**: right before a backup, `pg_dump` (or `tar` for ParkingClub's data) writes into a small `backup` folder (an emptyDir) that Velero does copy. A restore brings back the apps plus that dump; `bash scripts/velero-restore-db.sh dev` loads it. When the lab moves to NFS storage, Velero can copy the disks directly and this step goes away.

**Tested Nov 27, 2026:**

| Test | Result |
| --- | --- |
| `velero backup create test-2 --include-namespaces dev` | Completed: 279 items, 25 volumes, 7 of 7 database hooks ran |
| Delete a namespace (`velero-test`), then `velero restore create --from-backup demo-backup` | Namespace and pod back, Running, in under 30 seconds |

Velero's node agent runs on all three nodes (it tolerates the control-plane taint), so pods on cp1 can be backed up too.

### 5. Starting over: the full rebuild test

The real proof of a GitOps lab is deleting everything and getting it back. On Nov 27, 2026 the VMs were destroyed and rebuilt from the repo:

```bash
cd infra/libvirt && terraform apply                    # 3 fresh VMs
cd ../../ansible && ansible-playbook site.yml          # cluster + encryption + audit + CIS report
cd .. && export KUBECONFIG=$PWD/ansible/kubeconfig-lab
grep -vE '^\s+(resourceVersion|uid|creationTimestamp):' ~/homelab-keys/sealed-secrets-key.yaml | kubectl apply -f -
bash scripts/bootstrap-argocd.sh                        # Argo CD installs everything else from Git
```

Two problems found and fixed on the way, both now handled by the playbook:

| Problem | Why | Fix |
| --- | --- | --- |
| Ansible "No route to host" | It started 2 seconds after Terraform, while the VMs were still booting | `site.yml` first waits up to 10 minutes for SSH |
| `Unable to acquire the dpkg frontend lock` on w1 | A fresh Ubuntu VM runs automatic security updates on first boot | The `common` role waits for them; every apt step waits up to 15 minutes for the lock |

After the rebuild: trust the new lab CA in your browser again, set up 2FA again on the lab sites (new databases), and save the new `~/homelab-keys/encryption-config.yaml`.

### 6. Falco: runtime security

Everything above stops bad things from getting **in**. Falco watches what running pods actually **do**. It runs on every node and reads each container's system calls through modern eBPF, a safe kernel hook with nothing to compile. When something matches a rule, it writes an alert:

| You do this in a pod | Falco says |
| --- | --- |
| `kubectl exec -it … -- sh` | Terminal shell in container (Notice) |
| `cat /etc/shadow` | Read sensitive file untrusted (Warning) |
| write a file under `/etc` | File below /etc opened for writing (Error) |

Watch alerts with `kubectl -n falco logs ds/falco -f`, or run `bash scripts/falco-test.sh`: it makes a throwaway pod, does those three things, prints the alerts and cleans up. Alerts stay in the pod logs for now; Falcosidekick can send them to Slack, email or Grafana later.

**Client version:** "Admission policies stop bad workloads at the door; Falco is the security camera inside, and it tells me within seconds if someone opens a shell in a container."

## CI/CD: from a commit to a running pod

**CI** (GitHub Actions) tests and builds. **CD** (Argo CD) deploys.

| Workflow | Runs when | What it does |
| --- | --- | --- |
| validate | Every pull request and push to main | Terraform format check, renders and validates every Kustomize folder with kubeconform, syntax-checks Ansible and scripts |
| docs reminder | Every pull request | Warns when apps/platform/clusters/infra change but `docs/` doesn't |
| sitekit image | Push to main changing `apps/sitekit/app` | Tests, builds, pushes to ghcr.io, writes the new tag into the overlays |
| pc-lab runner image | Push to main changing `apps/parkingclub-lab/runner` | Builds, smoke-tests, pushes, writes the new tag |
| civic-hub image | Changes to Civic Hub's code | Tests and builds Civic Hub |

**Why tag images with the commit:** a tag like `edge` can point to different code tomorrow, so the cluster can't tell anything changed. A commit tag is unique. CI writes it into the overlay and commits (as `github-actions[bot]`, `[skip ci]`), Argo CD sees the Git change and rolls out. You always know exactly which code is running.

### Your three daily workflows

**1. Change a site's pages:** push to the site repo's `dev` branch → the lab copy shows it within ~5 minutes (2 for ParkingClub) → merge `dev` into `main` to go live. Keep `dev` current with `git checkout dev && git merge main && git push` (often in ask-canada, where Civic Hub updates `main` daily).

**2. Change sitekit or the ParkingClub runner:** `git pull` in homelab first (CI commits too), edit, push to `main` → Actions tests, builds, commits the new tag (a failed test stops it) → Argo CD rolls out within ~3 minutes.

**3. Change Kubernetes settings:** edit `apps/<app>/overlays/dev`, open a PR or push → `validate` checks → Argo CD applies.

**Rolling back** = `git revert <commit>` and push.

## Security, troubleshooting and cheat sheet

| Layer | Protection | Stops |
| --- | --- | --- |
| Network | Private libvirt network; only your desktop can reach the lab | Anyone outside your desktop |
| Entry | Traefik with HTTPS from lab-ca | Snooping on the connection |
| Between pods | NetworkPolicies (database only from its app; app only from Traefik) | A broken pod reaching other apps' data |
| Pod | Non-root, read-only filesystem, no capabilities, seccomp | A break-in gaining control of the node |
| Cluster rules | Kyverno policies (Audit) | Unsafe settings slipping in unnoticed |
| Secrets | Sealed Secrets; only the cluster can decrypt | Passwords leaking through the public repo |
| App | Hashed passwords, lockout, CSRF, invite-only sign-up, roles, audit log | Guessing, forged form posts, strangers signing up |
| Source | Read-only deploy key; secret scanning and push protection | Lab compromise changing code; keys pushed by accident |
| Change control | Everything through Git and CI tests | Untested or unrecorded changes |

Known gaps: Kyverno only *reports* (switch to `Enforce` once nothing breaks a rule), and the sealed-secrets private key exists only in the cluster. Encryption at rest and the audit log are covered by `ansible/security.yml`. Back it up somewhere safe, never in Git:

```
kubectl get secret -n kube-system -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > sealed-secrets-key.yaml
```

### Troubleshooting playbook (work from the outside in)

| You see | It means | Check |
| --- | --- | --- |
| Browser can't connect | /etc/hosts, the VMs or Traefik | `virsh list --all`, `kubectl get svc -n traefik` |
| `404 page not found` (plain text) | Traefik has no Ingress for that name | `kubectl get ingress -n dev`; merged and synced? |
| Certificate warning | Desktop doesn't trust lab-ca, or cert not ready | `kubectl get certificate -n dev` |
| App missing in Argo CD | Folder isn't `apps/<app>/overlays/<env>`, or not on main | `kubectl get applications -n argocd` |
| `CreateContainerConfigError` | A Secret or ConfigMap the pod needs doesn't exist | `kubectl get secrets -n dev`, `kubectl describe pod <name> -n dev` |
| `ImagePullBackOff` | Image missing or package private | GitHub Packages visibility; tag in the overlay |
| `CrashLoopBackOff` | App starts then dies | `kubectl logs <pod> -n dev -c <container> --previous` |
| PVC stuck `Pending` | No storage | `kubectl get sc` |
| Pod `Pending` | Not enough CPU or memory | `kubectl describe pod`, `kubectl top nodes` |

### Cheat sheet

| Task | Command |
| --- | --- |
| Start or stop the lab | `scripts/lab.sh start` · `scripts/lab.sh stop` |
| Snapshot and undo | `scripts/lab.sh snapshot <name>` · `scripts/lab.sh revert <name>` |
| Nodes healthy? | `kubectl get nodes` |
| Lab pods | `kubectl get pods -n dev` |
| Argo CD apps | `kubectl get applications -n argocd` |
| Re-read Git now | `kubectl -n argocd annotate applicationset workloads argocd.argoproj.io/refresh=true --overwrite` |
| Container logs | `kubectl logs -n dev deploy/ck-sitekit-web -c web` |
| Why is a pod unhappy? | `kubectl describe pod <name> -n dev` |
| Restart an app | `kubectl rollout restart deploy/ck-sitekit-web -n dev` |
| Open a site's database | `kubectl exec -it -n dev ck-sitekit-db-0 -- psql -U sitekit -d sitekit` |
| CPU and memory | `kubectl top nodes` · `kubectl top pods -n dev` |
| New sealed secret | `scripts/seal-sitekit.sh <site> dev <email>` |
| Turn on two-step login | open `/app/account/2fa` on any lab site |
| Security hardening + report | `cd ansible && ansible-playbook security.yml` |
| Velero on S3 (first time) | `bash scripts/aws-velero-bootstrap.sh <bucket> ca-central-1` |
| Ops panel guard in place? | `kubectl get validatingadmissionpolicy ck-sitekit-ops-tenants-only` |

### The one-minute client explanation

"I run a production-style Kubernetes platform. The servers and the cluster are built from code, so they can be rebuilt identically. Every app is deployed through Git with GitOps: changes are reviewed, tested in CI, applied automatically by Argo CD, and rolled back by reverting a commit. Every app gets HTTPS, encrypted secrets, network isolation and hardened containers by default, and policies check all of it. New code is tried in a dev copy first, with its own logins and database, before anything touches the live site. The same design moves to AWS EKS with only the bottom layer changing."
