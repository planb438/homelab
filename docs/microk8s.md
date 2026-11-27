# MicroK8s option — legacy, not used

> **Status (2026-11-27):** not used any more. The lab is built only with KVM/libvirt + Terraform + Ansible/kubeadm + Argo CD (see the README and `docs/lab-guide.md`). These notes stay for reference.

Use when you want a quick single-node cluster instead of the kubeadm lab (not at the same time — RAM).

```bash
# one VM (4 vCPU, 8 GB) or later a cloud VM
sudo snap install microk8s --classic
sudo microk8s enable dns hostpath-storage metallb:192.168.122.240-192.168.122.250 metrics-server
sudo microk8s config > ~/.kube/microk8s
```
Point Argo CD at the same `apps/` overlays (copy `clusters/lab` → `clusters/microk8s`, drop `platform/local-path`
and MetalLB apps because the add-ons replace them). `hostpath-storage` is the default StorageClass there.
