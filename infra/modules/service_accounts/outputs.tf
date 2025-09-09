# infra/modules/service_accounts/outputs.tf

output "runtime_service_accounts" {
  description = "Map of service names to their service account emails"
  value = {
    for name, sa in google_service_account.runtime :
    name => sa.email
  }
}

output "service_account_ids" {
  description = "Map of service names to their service account IDs"
  value = {
    for name, sa in google_service_account.runtime :
    name => sa.id
  }
}

# Individual outputs for convenience
output "idp_sa_email" {
  description = "June IDP service account email"
  value       = google_service_account.runtime["june-idp"].email
}

output "orchestrator_sa_email" {
  description = "June Orchestrator service account email"
  value       = google_service_account.runtime["june-orchestrator"].email
}

output "stt_sa_email" {
  description = "June STT service account email"
  value       = google_service_account.runtime["june-stt"].email
}

output "tts_sa_email" {
  description = "June TTS service account email"
  value       = google_service_account.runtime["june-tts"].email
}

output "nginx_sa_email" {
  description = "Nginx Edge service account email"
  value       = google_service_account.runtime["nginx-edge"].email
}