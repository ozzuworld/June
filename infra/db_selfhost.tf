# Inputs
variable "kc_admin_password" {
  type      = string
  sensitive = true
}

variable "kc_db_user" {
  type    = string
  default = "keycloak"
}

variable "kc_db_password" {
  type      = string
  sensitive = true
}

variable "kc_db_name" {
  type    = string
  default = "keycloak"
}

# Self-hosted Postgres VM module call (you should already have this)
# module "db_vm" { ... }

# Firewall (allow only internal subnet to reach Postgres)
# resource "google_compute_firewall" "allow_pg_internal" { ... }

# Secret Manager: store KC admin + DB password (single place!)
resource "google_secret_manager_secret" "kc_admin_password" {
  secret_id = "kc-admin-password"
  replication { automatic = true }
}
resource "google_secret_manager_secret_version" "kc_admin_password_v" {
  secret      = google_secret_manager_secret.kc_admin_password.id
  secret_data = var.kc_admin_password
}

resource "google_secret_manager_secret" "kc_db_password" {
  secret_id = "kc-db-password"
  replication { automatic = true }
}
resource "google_secret_manager_secret_version" "kc_db_password_v" {
  secret      = google_secret_manager_secret.kc_db_password.id
  secret_data = var.kc_db_password
}

# Locals used by Keycloak service
locals {
  kc_hostname = "auth.${var.domain}"
  kc_db_url   = "jdbc:postgresql://${module.db_vm.internal_ip}:5432/${var.kc_db_name}"
}
