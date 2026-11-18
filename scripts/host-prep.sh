#!/usr/bin/env bash
# One-time host setup for the lab (Ubuntu desktop). Safe to re-run.
set -euo pipefail
sudo apt-get update
sudo apt-get install -y qemu-kvm libvirt-daemon-system libvirt-clients virtinst ansible genisoimage
sudo usermod -aG libvirt,kvm "$USER"
virsh -c qemu:///system pool-info default >/dev/null 2>&1 || {
  virsh -c qemu:///system pool-define-as default dir --target /var/lib/libvirt/images
  virsh -c qemu:///system pool-start default
  virsh -c qemu:///system pool-autostart default
}
# Shrink the default network's DHCP range so static node IPs (.10-.12) and MetalLB (.240-.250) never collide.
if virsh -c qemu:///system net-dumpxml default | grep -q "end='192.168.122.254'"; then
  virsh -c qemu:///system net-update default delete ip-dhcp-range "<range start='192.168.122.2' end='192.168.122.254'/>" --live --config
  virsh -c qemu:///system net-update default add ip-dhcp-range "<range start='192.168.122.100' end='192.168.122.199'/>" --live --config
fi
ansible-galaxy collection install -r "$(dirname "$0")/../ansible/requirements.yml"
[ -f ~/.ssh/id_ed25519.pub ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519
echo "Done. Log out and back in (libvirt group), install Terraform, then: cd infra/libvirt && terraform init && terraform apply"
