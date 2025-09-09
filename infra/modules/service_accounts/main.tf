# infra/envs/quarterly/service_accounts.tf
# NEW FILE - Creates all runtime service accounts in one place
# This replaces secrets.tf and sa_runtime.tf to eliminate conflicts

locals {
  # Service configuration - matches your deploy.yml expectations  
  services = {
    "june-idp" = {
      account_suffix = "svc" # Creates june-idp-svc@project.iam
      secrets        = ["KC_DB_PASSWORD"]
    }
    "nginx-edge" = {
      account_suffix = "svc" # Creates nginx-edge-svc@project.iam
      secrets        = []
    }
    "june-orchestrator" = {
      account_suffix = "svc" # Creates orchestrator-svc@project.iam (matches deploy.yml)
      secrets        = ["NEON_DB_URL", "GEMINI_API_KEY"]
    }
    "june-stt" = {
      account_suffix = "svc" # Creates stt-svc@project.iam
      secrets        = ["GEMINI_API_KEY"]
    }
    "june-tts" = {
      account_suffix = "svc" # Creates tts-svc@project.iam
      secrets        = ["GEMINI_API_KEY"]
    }
  }

  # Flatten service-secret pairs for IAM binding
  service_secret_pairs = flatten([
    for service_name, config in local.services : [
      for secret in config.secrets : {
        service  = service_name
        secret   = secret
        sa_email = google_service_account.runtime[service_name].email
      }
    ]
  ])
}

# Create runtime service accounts (matches your deploy.yml naming)
resource "google_service_account" "runtime" {
  for_each = local.services

  project      = var.project_id
  account_id   = each.key == "june-orchestrator" ? "orchestrator-svc" : "${replace(each.key, "june-", "")}-svc"
  display_name = "Runtime SA for ${each.key}"
}

# Create secrets that don't exist yet
resource "google_secret_manager_secret" "kc_db_password" {
  project   = var.project_id
  secret_id = "KC_DB_PASSWORD"

  replication {
    auto {}
  }
}

# Grant secret access - least privilege per service
resource "google_secret_manager_secret_iam_member" "service_secrets" {
  for_each = {
    for pair in local.service_secret_pairs :
    "${pair.service}-${pair.secret}" => pair
  }

  project   = var.project_id
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.sa_email}"
}

# Outputs for main.tf
output "runtime_service_accounts" {
  description = "Runtime service account emails"
  value = {
    for name, sa in google_service_account.runtime :
    name => sa.email
  }
}