#!/usr/bin/env bash
# One-time host setup for the lab (Ubuntu 24.04 / 26.04 desktop). Safe to re-run.
# Run as YOUR user (not root):  bash scripts/host-prep.sh
set -euo pipefail
[ "$(id -u)" -eq 0 ] && { echo "Run as your normal user, not root (the script uses sudo itself)."; exit 1; }
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== 1/6 Packages (KVM, libvirt, Ansible)"
sudo apt-get update
# qemu-kvm is only a virtual package on Ubuntu 26.04 -> install qemu-system-x86 directly
sudo apt-get install -y qemu-system-x86 qemu-utils libvirt-daemon-system libvirt-clients virtinst \
  ansible genisoimage curl gnupg

echo "== 2/6 Your user in the libvirt + kvm groups"
sudo usermod -aG libvirt,kvm "$USER"

echo "== 3/6 Let QEMU open Terraform's linked disk images (Ubuntu AppArmor blocks the backing file)"
if ! sudo grep -q '^security_driver' /etc/libvirt/qemu.conf; then
  echo 'security_driver = "none"' | sudo tee -a /etc/libvirt/qemu.conf >/dev/null
fi
sudo systemctl restart libvirtd 2>/dev/null || sudo systemctl restart virtqemud

echo "== 4/6 Storage pool + network (uses sudo, so it works before you log out/in)"
sudo virsh pool-info default >/dev/null 2>&1 || {
  sudo virsh pool-define-as default dir --target /var/lib/libvirt/images
  sudo virsh pool-build default || true
  sudo virsh pool-start default
  sudo virsh pool-autostart default
}
sudo virsh net-autostart default >/dev/null
sudo virsh net-start default 2>/dev/null || true
# Shrink DHCP so static node IPs (.10-.12) and MetalLB (.240-.250) never collide.
if sudo virsh net-dumpxml default | grep -q "end='192.168.122.254'"; then
  sudo virsh net-update default delete ip-dhcp-range "<range start='192.168.122.2' end='192.168.122.254'/>" --live --config
  sudo virsh net-update default add ip-dhcp-range "<range start='192.168.122.100' end='192.168.122.199'/>" --live --config
fi

echo "== 5/6 Terraform (HashiCorp apt repo)"
if ! command -v terraform >/dev/null; then
  curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo gpg --dearmor --yes -o /usr/share/keyrings/hashicorp-archive-keyring.gpg
  CODENAME="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
  # fall back to noble (24.04) if HashiCorp has no folder for this release yet
  curl -fsI "https://apt.releases.hashicorp.com/dists/${CODENAME}/Release" >/dev/null || CODENAME=noble
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/hashicorp-archive-keyring.gpg] https://apt.releases.hashicorp.com ${CODENAME} main" \
    | sudo tee /etc/apt/sources.list.d/hashicorp.list >/dev/null
  sudo apt-get update && sudo apt-get install -y terraform
fi

echo "== 5b kubectl on the host (matches the cluster's minor version)"
command -v kubectl >/dev/null || sudo snap install kubectl --classic --channel=1.34/stable

echo "== 6/6 Ansible collections + SSH key"
ansible-galaxy collection install -r "$REPO_DIR/ansible/requirements.yml"
[ -f ~/.ssh/id_ed25519.pub ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519

echo
echo "Done. NOW LOG OUT AND BACK IN (or reboot) so the libvirt group applies, then check:"
echo "  groups | grep -q libvirt && virsh -c qemu:///system list --all"
echo "Then: cd $REPO_DIR/infra/libvirt && terraform init && terraform apply"
