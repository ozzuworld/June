# Store the admin + DB password in Secret Manager, and give the service SA access via your module.
resource "google_secret_manager_secret" "kc_admin_password" {
  secret_id  = "kc-admin-password"
  replication { automatic = true }
}

resource "google_secret_manager_secret_version" "kc_admin_password_v" {
  secret      = google_secret_manager_secret.kc_admin_password.id
  secret_data = var.kc_admin_password
}

resource "google_secret_manager_secret" "kc_db_password" {
  secret_id  = "kc-db-password"
  replication { automatic = true }
}

resource "google_secret_manager_secret_version" "kc_db_password_v" {
  secret      = google_secret_manager_secret.kc_db_password.id
  secret_data = var.kc_db_password
}
