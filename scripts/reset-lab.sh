#!/usr/bin/env bash
# Wipe the lab VMs and disks so you can rebuild from scratch. Touches ONLY cp1, w1, w2 and their images.
# Usage: bash scripts/reset-lab.sh
set -uo pipefail
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR/infra/libvirt"
terraform destroy -auto-approve || echo "terraform destroy had errors - cleaning up by hand below"
for n in cp1 w1 w2; do
  sudo virsh destroy "$n" 2>/dev/null
  sudo virsh undefine "$n" --remove-all-storage --snapshots-metadata 2>/dev/null
  for v in "$n.qcow2" "$n-init.iso"; do sudo virsh vol-delete "$v" --pool default 2>/dev/null; done
done
sudo virsh vol-delete ubuntu-noble-base.qcow2 --pool default 2>/dev/null
rm -f terraform.tfstate terraform.tfstate.backup
rm -f "$REPO_DIR/ansible/kubeconfig-lab"
for ip in 192.168.122.10 192.168.122.11 192.168.122.12; do ssh-keygen -R "$ip" >/dev/null 2>&1; done
echo "Clean. Rebuild with: cd infra/libvirt && terraform apply"
sudo virsh list --all
