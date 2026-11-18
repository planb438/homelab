# Lab 02 — Network policies (zero trust inside the cluster)

| | Old lab (Network-Policy-Learning-Environment, 06-network-policies) | This version |
|---|---|---|
| Start | Pods could talk to anything; policies added one at a time | **Default deny in and out**, then allow only what is needed |
| DNS | Often broke when egress was denied | Explicit `allow-dns` to CoreDNS only |
| Allow rules | One side only | Both sides: web allows *from* client, client allows *to* web |
| Test | `test-connection.sh` read by eye | `tests/test.sh` → PASS/FAIL |

**What it shows a client:** a compromised pod (`intruder`) can't reach the app or the internet; only the intended path works.

**Needs:** a CNI that enforces NetworkPolicy — **Calico** here (Flannel would silently ignore them).

**Test:** `bash labs/02-network-policy/tests/test.sh`

**On AWS / EKS:** same YAML. Turn on network policy in the VPC CNI (`enableNetworkPolicy: "true"`) or keep Calico.
