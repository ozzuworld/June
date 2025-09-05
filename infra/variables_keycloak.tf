variable "domain" {
  description = "Base domain used for public endpoints (e.g., example.com)"
  type        = string
}

variable "kc_version" {
  description = "Keycloak version tag from the official repo"
  type        = string
  default     = "24.0"
}

variable "kc_admin_password" {
  description = "Bootstrap admin password for Keycloak (used once)"
  type        = string
  sensitive   = true
}

variable "kc_min_instances" {
  description = "Min Cloud Run instances for the auth service"
  type        = number
  default     = 1
}

variable "kc_max_instances" {
  description = "Max Cloud Run instances for the auth service"
  type        = number
  default     = 5
}

# If you're using an EXTERNAL Postgres (recommended for quick, portable start):
variable "kc_db_host" {
  description = "Postgres host (external provider or self-hosted)"
  type        = string
}

variable "kc_db_port" {
  description = "Postgres port"
  type        = number
  default     = 5432
}

variable "kc_db_name" {
  description = "Postgres database name for Keycloak"
  type        = string
  default     = "keycloak"
}

variable "kc_db_user" {
  description = "Postgres username for Keycloak"
  type        = string
}

variable "kc_db_password" {
  description = "Postgres password for Keycloak"
  type        = string
  sensitive   = true
}

locals {
  kc_hostname = "auth.${var.domain}"
  kc_db_url   = "jdbc:postgresql://${var.kc_db_host}:${var.kc_db_port}/${var.kc_db_name}"
}
