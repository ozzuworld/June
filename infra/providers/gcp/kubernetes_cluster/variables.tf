variable "project_id"   { type = string }
variable "name"         { type = string }
variable "region"       { type = string }
variable "k8s_version"  { type = string }
variable "node_pools" {
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
