resource "google_service_account" "idp_sa" {
  account_id   = "june-idp-sa"
  display_name = "June IDP Cloud Run SA"
}

resource "google_secret_manager_secret" "kc_db_password" {
  secret_id = "KC_DB_PASSWORD"

  replication {
    automatic = true # CORRECT - this is an argument
  }
}
resource "google_secret_manager_secret_iam_member" "kc_db_pw_access" {
  secret_id = google_secret_manager_secret.kc_db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.idp_sa.email}"
}
