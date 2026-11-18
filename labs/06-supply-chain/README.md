# Lab 06 — Supply chain: which images may run

| | Old labs (07-private-registry, 08-cosign, kyverno `disallow-latest-tag`) | This version |
|---|---|---|
| Tags | `:latest` common | `:latest` refused (Enforce) |
| Registries | anything | allow-list (ghcr.io, registry.k8s.io, quay.io, nginxinc) |
| Digests / signatures | cosign lab done by hand | Digest rule in **Audit** now; next: Kyverno `verifyImages` with cosign |
| Scope | ClusterPolicy across everything | Namespaced `Policy` — safe to experiment, can't break the platform |

**Test:** `bash labs/06-supply-chain/tests/test.sh`

**On AWS / EKS:** same policies; add your **ECR** registry to the allow-list and turn on ECR image scanning.
