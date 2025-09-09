# ---- Inputs (match your env) ----
variable "project_id" {
  type = string
}

# The SA you use in GitHub Actions with WIF (same as secrets.DEPLOYER_SA)
# e.g. "deployer@main-buffer-469817-v7.iam.gserviceaccount.com"
variable "deployer_sa_email" {
  type = string
}

# Which services need runtime SAs
locals {
  services = toset([
    "june-idp",
    "nginx-edge",
    "june-orchestrator",
    "june-stt",
    "june-tts",
  ])
}

# ---- Runtime Service Accounts (one per service) ----
resource "google_service_account" "runtime" {
  for_each     = local.services
  account_id   = "${replace(each.key, "_", "-")}-svc" # e.g. nginx-edge-svc
  display_name = "Runtime SA for ${each.key}"
  project      = var.project_id
}

# Allow the GitHub deployer SA to act as each runtime SA
resource "google_service_account_iam_member" "deployer_actas" {
  for_each           = local.services
  service_account_id = google_service_account.runtime[each.key].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deployer_sa_email}"
}

# ---- Secret Manager access for Keycloak (june-idp) only ----
# So that the Keycloak runtime can read KC_DB_PASSWORD at deploy/runtime.
# If the secret doesn't exist yet, create it elsewhere first (you already have it).
data "google_secret_manager_secret" "kc_db_password" {
  project   = var.project_id
  secret_id = "KC_DB_PASSWORD"
}

resource "google_secret_manager_secret_iam_member" "idp_secret_accessor" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.kc_db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime["june-idp"].email}"
}

# (Optional) If you store other secrets per service, add similar IAM members here.

# ---- Helpful outputs ----
output "runtime_service_accounts" {
  value = {
    for k, sa in google_service_account.runtime :
    k => sa.email
  }
}

output "nginx_edge_sa_email" {
  value = google_service_account.runtime["nginx-edge"].email
}

output "june_idp_sa_email" {
  value = google_service_account.runtime["june-idp"].email
}
