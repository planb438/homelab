# Lab 03 — Secrets in Git, done safely (Sealed Secrets)

| | Old repos (odoo, snipe-it, wordpress, dolibarr, velero in `argocd-applications-homelab`) | This version |
|---|---|---|
| Where the password lives | Plain `kind: Secret` with `stringData` **committed to a public repo** | `SealedSecret` — encrypted with the cluster's public key; only the controller can decrypt |
| Who can read it | Anyone who can see GitHub | Only the cluster (private key never leaves `kube-system`) |
| Rotation | Edit the file, password in history forever | Re-seal and commit; old ciphertext is useless without the key |

**Step 1 – install kubeseal on your desktop (once):**
```bash
KS=0.41.2; curl -sSL https://github.com/bitnami-labs/sealed-secrets/releases/download/v$KS/kubeseal-$KS-linux-amd64.tar.gz | tar xz kubeseal
sudo install -m 755 kubeseal /usr/local/bin/ && rm kubeseal
```
**Step 2 – make, seal and commit a secret (the plain one never touches disk):**
```bash
kubectl create secret generic app-credentials -n lab-03-sealed-secrets \
  --from-literal=DB_PASSWORD="$(openssl rand -base64 24)" --dry-run=client -o yaml \
| kubeseal -o yaml > labs/03-sealed-secrets/sealedsecret.yaml
# add "- sealedsecret.yaml" to labs/03-sealed-secrets/kustomization.yaml, commit, push, merge
```
**Step 3 – test:** `bash labs/03-sealed-secrets/tests/test.sh`

**Back up the sealing key** (or a rebuilt cluster can't decrypt your Git secrets):
`kubectl -n kube-system get secret -l sealedsecrets.bitnami.com/sealed-secrets-key -o yaml > ~/sealed-secrets-key.yaml` → store in your password manager, **never in Git**.

**Old repos:** `argocd-applications-homelab` still has real-looking passwords in plain Secrets (and `aws-k8s-lab` has etcd snapshots). Treat those passwords as leaked: change them anywhere they're still used.

**On AWS / EKS:** use **External Secrets Operator + AWS Secrets Manager** (IRSA, no keys in the cluster). Sealed Secrets also works unchanged.
