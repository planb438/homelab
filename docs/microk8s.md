# MicroK8s option (easy add-ons)

Use when you want a quick single-node cluster instead of the kubeadm lab (not at the same time — RAM).

```bash
# one VM (4 vCPU, 8 GB) or later a cloud VM
sudo snap install microk8s --classic
sudo microk8s enable dns hostpath-storage metallb:192.168.122.240-192.168.122.250 metrics-server
sudo microk8s config > ~/.kube/microk8s
```
Point Argo CD at the same `apps/` overlays (copy `clusters/lab` → `clusters/microk8s`, drop `platform/local-path`
and MetalLB apps because the add-ons replace them). `hostpath-storage` is the default StorageClass there.
