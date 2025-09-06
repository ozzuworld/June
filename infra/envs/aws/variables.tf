variable "region" {
  type = string
  default = "us-east-1"
}

variable "name" {
  type = string
  default = "june-platform"
}

variable "k8s_version" {
  type = string
  default = "1.30"
}

variable "vpc_cidr" {
  type = string
  default = "10.42.0.0/16"
}

variable "node_pools" {
  type = list(object({
  name = string
  machine = string
  min = number
  max = number
  disk_gb = number
  spot = bool
}
))
  default = [{
    name="general", machine="t3.large", min=1, max=2, disk_gb=100, spot=true
  }]
}
variable "dns_zone_name" {
  type = string
  default = "home-example-com"
}

variable "domain" {
  type = string
  default = "home.example.com"
}

