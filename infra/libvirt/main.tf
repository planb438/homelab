terraform {
  required_version = ">= 1.6"
  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "~> 0.8.1"
    }
  }
}

provider "libvirt" {
  uri = "qemu:///system"
}

resource "libvirt_volume" "base" {
  name   = "ubuntu-noble-base.qcow2"
  pool   = var.pool
  source = var.image_url
  format = "qcow2"
}

resource "libvirt_volume" "disk" {
  for_each       = var.nodes
  name           = "${each.key}.qcow2"
  pool           = var.pool
  base_volume_id = libvirt_volume.base.id
  size           = each.value.disk_gb * 1024 * 1024 * 1024
}

resource "libvirt_cloudinit_disk" "init" {
  for_each = var.nodes
  name     = "${each.key}-init.iso"
  pool     = var.pool
  user_data = templatefile("${path.module}/cloud-init/user-data.yaml.tftpl", {
    hostname = each.key
    ssh_key  = trimspace(file(pathexpand(var.ssh_public_key)))
  })
  network_config = templatefile("${path.module}/cloud-init/network-config.yaml.tftpl", {
    ip      = each.value.ip
    gateway = var.gateway
  })
}

resource "libvirt_domain" "node" {
  for_each  = var.nodes
  name      = each.key
  memory    = each.value.memory_mb
  vcpu      = each.value.vcpu
  cloudinit = libvirt_cloudinit_disk.init[each.key].id
  autostart = false

  cpu {
    mode = "host-passthrough"
  }

  network_interface {
    network_name   = "default"
    addresses      = [each.value.ip]
    wait_for_lease = false
  }

  disk {
    volume_id = libvirt_volume.disk[each.key].id
  }

  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }
}
