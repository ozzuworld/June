# infra/envs/quarterly/service_accounts.tf
# Service accounts - CHATTERBOX TTS ONLY

locals {
  # Define all services that need runtime service accounts
  services = {
    "june-orchestrator" = {
      account_id   = "orchestrator-svc"
      display_name = "June Orchestrator Runtime SA"
    }
    "june-stt" = {
      account_id   = "stt-svc"
      display_name = "June STT Runtime SA"
    }
    # ONLY Chatterbox TTS - no other TTS services
    "june-chatterbox-tts" = {
      account_id   = "chatterbox-tts-svc"
      display_name = "June Chatterbox TTS Runtime SA"
    }
    "nginx-edge" = {
      account_id   = "nginx-edge-svc"
      display_name = "Nginx Edge Runtime SA"
    }
  }
}

# Create runtime service accounts
resource "google_service_account" "runtime" {
  for_each = local.services
  
  project      = var.project_id
  account_id   = each.value.account_id
  display_name = each.value.display_name
}

# Allow the deployer SA to impersonate runtime SAs (for GitHub Actions)
resource "google_service_account_iam_member" "deployer_can_impersonate" {
  for_each = var.deployer_sa_email != "" ? local.services : {}
  
  service_account_id = google_service_account.runtime[each.key].name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deployer_sa_email}"
}

# Output for use in main.tf
locals {
  runtime_service_accounts = {
    for name, sa in google_service_account.runtime :
    name => sa.email
  }
}