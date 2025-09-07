
resource "google_service_account" "orchestrator" {
  project    = var.project_id
  account_id = "orchestrator-svc"
  display_name = "Orchestrator runtime"
}
resource "google_service_account" "stt" {
  project    = var.project_id
  account_id = "stt-svc"
  display_name = "STT runtime"
}
resource "google_service_account" "tts" {
  project    = var.project_id
  account_id = "tts-svc"
  display_name = "TTS runtime"
}

resource "google_service_account_iam_member" "deployer_can_impersonate_runtime" {
  for_each = {
    orchestrator = google_service_account.orchestrator.name
    stt          = google_service_account.stt.name
    tts          = google_service_account.tts.name
  }
  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.github_deployer.email}"
}
