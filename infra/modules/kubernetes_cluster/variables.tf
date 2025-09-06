variable "name"        { type = string }
variable "region"      { type = string }
variable "k8s_version" { type = string }
variable "node_pools" {
  description = "List of pools with {name, machine, min, max, disk_gb, spot}"
  type = list(object({
    name     = string
    machine  = string
    min      = number
    max      = number
    disk_gb  = number
    spot     = bool
  }))
}
variable "network_id" { type = string }
variable "subnet_id"  { type = string }
