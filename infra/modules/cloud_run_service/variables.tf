variable "service_name" {
  description = "Name of the Cloud Run service"
  type        = string
}

variable "region" {
  description = "GCP region to deploy the service"
  type        = string
}

variable "image" {
  description = "Container image to deploy"
  type        = string
}

variable "args" {
  type    = list(string)
  default = []
}

variable "env" {
  type    = map(string)
  default = {}
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "1Gi"
}

variable "port" {
  type    = number
  default = 8080
}

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type    = number
  default = 20
}

variable "env_secrets" {
  description = "Map of secret envs: name => { secret = \"name\", version = \"latest\" }"
  type = map(object({
    secret  = string
    version = string
  }))
  default = {}
}

variable "session_affinity" {
  description = "Enable Cloud Run session affinity (sticky sessions)"
  type        = bool
  default     = false
}

variable "service_account" {
  description = "Service account email to run the service as (optional)"
  type        = string
  default     = null
}