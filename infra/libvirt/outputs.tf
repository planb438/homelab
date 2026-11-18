output "nodes" {
  value = { for k, v in var.nodes : k => v.ip }
}
