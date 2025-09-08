# Service account and Secret Manager IAM for the june-idp Cloud Run service

# Runtime service account for june-idp (email: june-idp-svc@<project>.iam.gserviceaccount.com)
resource "google_service_account" "june_idp" {
  project      = var.project_id
  account_id   = "june-idp-svc"
  display_name = "June IDP runtime"
}

# Allow the GitHub deployer SA to impersonate the runtime SA (same as other runtime SAs)
resource "google_service_account_iam_member" "deployer_can_impersonate_june_idp" {
  service_account_id = google_service_account.june_idp.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deployer.email}"
}

# Reference existing KC_DB_PASSWORD secret (we do NOT create it here)
data "google_secret_manager_secret" "kc_db_password" {
  project   = var.project_id
  secret_id = "KC_DB_PASSWORD"
}

# Runtime SA can READ the secret value (runtime)
resource "google_secret_manager_secret_iam_member" "june_idp_secret_accessor" {
  secret_id = data.google_secret_manager_secret.kc_db_password.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.june_idp.email}"
}

# Deployer SA can SEE secret metadata at deploy-time (needed by --set-secrets during gcloud run deploy)
resource "google_secret_manager_secret_iam_member" "deployer_can_view_kcdb" {
  secret_id = data.google_secret_manager_secret.kc_db_password.id
  role      = "roles/secretmanager.viewer"
  member    = "serviceAccount:${google_service_account.github_deployer.email}"
}
