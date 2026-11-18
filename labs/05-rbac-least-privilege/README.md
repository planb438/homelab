# Lab 05 — RBAC & service accounts (least privilege)

| | Old repos (velero `cluster-admin`, 12/13-sa-abuse-prevention) | This version |
|---|---|---|
| Permissions | `ClusterRoleBinding` to `cluster-admin` "to make it work" | A `Role` limited to **one named object and one verb** |
| Tokens | Every pod got an API token automatically | `automountServiceAccountToken: false` by default |
| Proof | Manual `kubectl auth can-i` | `tests/test.sh` checks allowed **and** denied actions |

**Test:** `bash labs/05-rbac-least-privilege/tests/test.sh`

**On AWS / EKS:** same RBAC. Add **IRSA / EKS Pod Identity** so a pod gets an IAM role for AWS APIs instead of access keys.
