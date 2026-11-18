#!/usr/bin/env bash
# Installs Argo CD, then hands the cluster to Git (clusters/lab/root.yaml).
set -euo pipefail
: "${KUBECONFIG:?export KUBECONFIG=ansible/kubeconfig-lab first}"
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -n argocd --server-side --force-conflicts \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
kubectl apply -f "$(dirname "$0")/../clusters/lab/root.yaml"
echo "Argo CD admin password:"
kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath="{.data.password}" | base64 -d; echo
echo "UI: kubectl -n argocd port-forward svc/argocd-server 8080:443  →  https://localhost:8080"
