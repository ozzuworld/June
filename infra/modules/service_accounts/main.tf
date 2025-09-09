# infra/modules/service_accounts/main.tf
# This module creates runtime service accounts for all June services

locals {
  # Define all services that need runtime service accounts
  services = {
    "june-idp" = {
      account_id   = "idp-svc"
      display_name = "June IDP Runtime SA"
      secrets      = ["KC_DB_PASSWORD"]
    }
    "june-orchestrator" = {
      account_id   = "orchestrator-svc"
      display_name = "June Orchestrator Runtime SA"
      secrets      = []
    }
    "june-stt" = {
      account_id   = "stt-svc"
      display_name = "June STT Runtime SA"
      secrets      = []
    }
    "june-tts" = {
      account_id   = "tts-svc"
      display_name = "June TTS Runtime SA"
      secrets      = []
    }
    "nginx-edge" = {
      account_id   = "nginx-edge-svc"
      display_name = "Nginx Edge Runtime SA"
      secrets      = []
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
