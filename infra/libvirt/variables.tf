variable "pool" {
  type    = string
  default = "default"
}

variable "image_url" {
  type    = string
  default = "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-amd64.img"
}

variable "ssh_public_key" {
  type    = string
  default = "~/.ssh/id_ed25519.pub"
}

variable "gateway" {
  type    = string
  default = "192.168.122.1"
}

# Sized for an 18 GB host that is also a desktop: 11 GB to the cluster, ~7 GB left.
variable "nodes" {
  type = map(object({
    ip        = string
    vcpu      = number
    memory_mb = number
    disk_gb   = number
  }))
  default = {
    cp1 = { ip = "192.168.122.10", vcpu = 2, memory_mb = 3072, disk_gb = 30 }
    w1  = { ip = "192.168.122.11", vcpu = 2, memory_mb = 4096, disk_gb = 60 }
    w2  = { ip = "192.168.122.12", vcpu = 2, memory_mb = 4096, disk_gb = 60 }
  }
}
