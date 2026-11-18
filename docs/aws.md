# AWS EKS phase

Keep: `apps/`, `policies/`, the promotion flow.
Add:
* `infra/aws/` — Terraform from `EKS-Terraform-Lab`: VPC, EKS, IRSA, EBS CSI (gp3 default StorageClass),
  remote state in S3 + DynamoDB lock.
* `clusters/eks/` — same pattern as `clusters/lab/` without local-path and MetalLB; add AWS Load Balancer
  Controller (or Traefik behind an NLB), external-dns, cert-manager with Route 53.
* Cost guardrails before anything else: AWS Budgets alert, small node group (t3.medium spot), `terraform destroy`
  when idle. Old lab accounts ran past free tier — avoid a repeat.
