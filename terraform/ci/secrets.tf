
resource "google_secret_manager_secret" "app" {
  for_each  = toset(var.secrets)
  project   = var.project_id
  secret_id = each.value

  replication {
    auto {}   # <-- v5+ syntax (replaces: automatic = true)
  }
}


resource "google_secret_manager_secret_iam_member" "orchestrator_access" {
  for_each = google_secret_manager_secret.app
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orchestrator.email}"
}
resource "google_secret_manager_secret_iam_member" "stt_access" {
  for_each = google_secret_manager_secret.app
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.stt.email}"
}
resource "google_secret_manager_secret_iam_member" "tts_access" {
  for_each = google_secret_manager_secret.app
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.tts.email}"
}
