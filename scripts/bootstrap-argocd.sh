#!/usr/bin/env bash
# Installs Argo CD, then hands the cluster to Git (clusters/lab/root.yaml).
set -euo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$REPO_DIR/ansible/kubeconfig-lab}"
[ -f "$KUBECONFIG" ] || { echo "No kubeconfig at $KUBECONFIG - run the Ansible playbook first."; exit 1; }
command -v kubectl >/dev/null || { echo "kubectl missing: sudo snap install kubectl --classic --channel=1.34/stable"; exit 1; }
kubectl get nodes
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
kubectl apply -f "$REPO_DIR/clusters/lab/root.yaml"
echo "Argo CD admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
echo "UI: kubectl -n argocd port-forward svc/argocd-server 8080:443  →  https://localhost:8080"
