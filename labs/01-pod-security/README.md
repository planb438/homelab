# Lab 01 — Pod security (PSA "restricted" + hardened securityContext)

| | Old lab (CKS-Walk-Thru-002 04/05) | This version |
|---|---|---|
| How | Good/bad pods applied by hand with `kubectl apply` | Namespace label enforces **Pod Security Admission: restricted**; Argo CD deploys only the good workload |
| Bad pods | Lived next to good ones in the same folder | Kept in `tests/`, only ever sent with `--dry-run=server` (nothing bad is created) |
| Proof | Read the error by eye | `tests/test.sh` prints PASS/FAIL |

**What it shows a client:** a workload can't run as root, escalate privileges, mount the host, or write to its own filesystem — enforced by Kubernetes itself, no extra tool.

**Settings that matter:** `pod-security.kubernetes.io/enforce: restricted` (namespace) · `runAsNonRoot`, `runAsUser: 101`, `seccompProfile: RuntimeDefault`, `allowPrivilegeEscalation: false`, `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`, `automountServiceAccountToken: false`.

**Test:** `bash labs/01-pod-security/tests/test.sh`

**On AWS / EKS:** identical — PSA is built into Kubernetes. Use the same namespace labels.
