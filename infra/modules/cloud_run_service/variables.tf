variable "project_id" { type = string }
variable "region" { type = string }
variable "service_name" { type = string }
variable "image" { type = string }

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

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "env" {
  type    = map(string)
  default = {}
}

# Secret env: { NAME = { secret = <sm_secret_id>, version = <sm_version> }, ... }
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
