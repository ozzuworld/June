variable "secrets" {
  type    = list(string)
  default = [
    "NEON_DB_URL", "NEON_API_KEY",
    "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "UPSTASH_REDIS_URL",
    "QDRANT_API_KEY", "QDRANT_URL",
    "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET",
    "CLOUDFLARE_API_TOKEN"
  ]
}

resource "google_secret_manager_secret" "app" {
  for_each  = toset(var.secrets)
  secret_id = each.value
  replication { auto {} }
}

resource "google_secret_manager_secret_iam_member" "runtime_access" {
  for_each = toset(var.secrets)
  secret_id = google_secret_manager_secret.app[each.key].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orchestrator.email}"
}
