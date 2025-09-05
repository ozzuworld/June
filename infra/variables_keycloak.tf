# ---- public DNS for Keycloak ----
variable "domain" {
  description = "Base domain (e.g., example.com)"
  type        = string
}

# ---- Keycloak container settings ----
variable "kc_version" {
  description = "Keycloak image tag"
  type        = string
  default     = "24.0"
}

variable "kc_min_instances" {
  description = "Min Cloud Run instances for Keycloak"
  type        = number
  default     = 1
}

variable "kc_max_instances" {
  description = "Max Cloud Run instances for Keycloak"
  type        = number
  default     = 5
}
