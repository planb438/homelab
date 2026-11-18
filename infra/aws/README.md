# AWS phase (placeholder)

When the AWS account is active, build EKS here by reusing modules from `EKS-Terraform-Lab`
(VPC → EKS → IRSA → EBS CSI). Then add `clusters/eks/` (copy of `clusters/lab/`, pointing at
the same `apps/` overlays). Differences to handle: default StorageClass `gp3`, load balancer
via AWS Load Balancer Controller, DNS via Route 53 / external-dns. See `docs/aws.md`.
