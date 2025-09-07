variable "project_id" {}
variable "project_number" {}
variable "github_org" {}
variable "github_repo" {}
variable "wif_pool_id" { default = "github-pool" }
variable "wif_provider_id" { default = "github-provider" }

resource "google_iam_workload_identity_pool" "github_pool" {
  project                   = var.project_id
  workload_identity_pool_id = var.wif_pool_id
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "github_provider" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github_pool.workload_identity_pool_id
  workload_identity_pool_provider_id = var.wif_provider_id
  display_name                       = "GitHub Provider"
  attribute_mapping = {
    "google.subject"        = "assertion.sub"
    "attribute.repository"  = "assertion.repository"
    "attribute.ref"         = "assertion.ref"
  }
  oidc { issuer_uri = "https://token.actions.githubusercontent.com" }
  attribute_condition = "attribute.repository == \"${var.github_org}/${var.github_repo}\""
}

resource "google_service_account" "github_deployer" {
  project      = var.project_id
  account_id   = "github-deployer"
  display_name = "GitHub CI/CD Deployer"
}

resource "google_service_account_iam_member" "wif_impersonation" {
  service_account_id = google_service_account.github_deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github_pool.workload_identity_pool_id}/attribute.repository/${var.github_org}/${var.github_repo}"
}

resource "google_project_iam_member" "run_admin" {
  project = var.project_id
  role    = "roles/run.admin"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_project_iam_member" "artifact_pusher" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_project_iam_member" "secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.github_deployer.email}"
}

resource "google_service_account" "orchestrator" { project = var.project_id  account_id = "orchestrator-svc" }
resource "google_service_account" "stt"          { project = var.project_id  account_id = "stt-svc" }
resource "google_service_account" "tts"          { project = var.project_id  account_id = "tts-svc" }

resource "google_service_account_iam_member" "deployer_can_impersonate_runtime" {
  for_each = { orchestrator = google_service_account.orchestrator.name, stt = google_service_account.stt.name, tts = google_service_account.tts.name }
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deployer.email}"
}
