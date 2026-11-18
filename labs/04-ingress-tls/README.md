# Lab 04 — Exposing apps: Ingress + TLS instead of NodePort

| | Old repos (odoo, wiki.js, snipe-it, wordpress, nextcloud, grafana, minio…) | This version |
|---|---|---|
| Exposure | `type: NodePort` → a high port open on **every node** | `ClusterIP` + one **Traefik** entry point (MetalLB IP) |
| TLS | none (plain http) | **cert-manager** issues a cert from the lab CA automatically |
| Guardrail | none | Kyverno refuses NodePort in this namespace; NetworkPolicy lets only Traefik in |

**Use it:** add `hello.lab.local` to the same `/etc/hosts` line as Argo CD, open https://hello.lab.local.
**Trust the lab CA (no more browser warnings):**
```bash
kubectl -n cert-manager get secret homelab-ca -o jsonpath='{.data.ca\.crt}' | base64 -d > homelab-ca.crt
sudo cp homelab-ca.crt /usr/local/share/ca-certificates/ && sudo update-ca-certificates
```
(Firefox/Chrome: also import it under Settings → Certificates → Authorities.)

**Test:** `bash labs/04-ingress-tls/tests/test.sh`

**On AWS / EKS:** same Ingress. Change only the issuer (`letsencrypt-prod`, Route 53 DNS-01) and the load balancer (AWS NLB in front of Traefik, or AWS Load Balancer Controller).
