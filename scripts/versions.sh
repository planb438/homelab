#!/usr/bin/env bash
# Prints the live versions of everything in the lab — paste the output into the Homelab HQ "Versions" tab.
set -uo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export KUBECONFIG="${KUBECONFIG:-$REPO_DIR/ansible/kubeconfig-lab}"
echo "# homelab versions — $(date -u +%Y-%m-%dT%H:%MZ)"
echo "## host"
echo "os: $(. /etc/os-release && echo "$PRETTY_NAME") · kernel $(uname -r)"
echo "terraform: $(terraform version 2>/dev/null | head -1)"
echo "ansible: $(ansible --version 2>/dev/null | head -1)"
echo "kubectl: $(kubectl version --client 2>/dev/null | head -1)"
echo "kubeseal: $(kubeseal --version 2>/dev/null || echo not installed)"
echo "## cluster"
kubectl version 2>/dev/null | grep -i server
kubectl get nodes -o custom-columns='NODE:.metadata.name,KUBELET:.status.nodeInfo.kubeletVersion,RUNTIME:.status.nodeInfo.containerRuntimeVersion,OS:.status.nodeInfo.osImage,KERNEL:.status.nodeInfo.kernelVersion'
echo "## argo cd applications (chart / revision actually synced)"
kubectl -n argocd get applications -o custom-columns='APP:.metadata.name,CHART:.spec.source.chart,WANTED:.spec.source.targetRevision,SYNCED:.status.sync.revision,SYNC:.status.sync.status,HEALTH:.status.health.status'
echo "## images running (per namespace)"
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{range .spec.containers[*]}{.image}{" "}{end}{"\n"}{end}' | sort -u
