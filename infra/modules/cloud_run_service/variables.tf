variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "service_name" {
  type = string
}

variable "image" {
  type = string
}

variable "allow_unauthenticated" {
  type    = bool
  default = true
}

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type    = number
  default = 10
}

# If your limits map expects strings, change type to string and default = "1"
variable "cpu" {
  type    = number
  default = 1
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "env" {
  type    = map(string)
  default = {}
}

# Secret env: { NAME = { secret = <sm_secret_id>, version = <sm_version> } }
variable "secret_env" {
  type = map(object({
    secret  = string
    version = string
  }))
  default = {}
}

# Optional annotations (e.g., Cloud SQL connector)
variable "annotations" {
  type    = map(string)
  default = {}
}

# VPC connector for private DB access
variable "vpc_connector" {
  type    = string
  default = ""
}

variable "vpc_egress" {
  type = string
  # "PRIVATE_RANGES_ONLY" or "ALL_TRAFFIC"
  default = "PRIVATE_RANGES_ONLY"
}

# Ingress policy for Cloud Run v2:
# "INGRESS_TRAFFIC_ALL" | "INGRESS_TRAFFIC_INTERNAL_ONLY" | "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
variable "ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_ALL"
}
