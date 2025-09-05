############################################
# june-auth: Secrets, APIs, Cloud Run
############################################

# Make sure required APIs exist (idempotent)
resource "google_project_service" "apis_june_auth" {
  for_each = toset([
    "firestore.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com"
  ])
  project = var.project_id
  service = each.key
}

# Secrets for june-auth
resource "google_secret_manager_secret" "june_auth_fernet_key" {
  secret_id = "${var.june_auth_service_name}-fernet-key"
  replication {
    automatic = true
  }
}

resource "google_secret_manager_secret" "june_auth_mfa_jwt_secret" {
  secret_id = "${var.june_auth_service_name}-mfa-jwt-secret"
  replication {
    automatic = true
  }
}

# (Optional) Add secret versions from variables (⚠️ writes secret material into TF state)
resource "google_secret_manager_secret_version" "june_auth_fernet_key" {
  count       = var.june_auth_create_secret_versions && var.june_auth_fernet_key != null ? 1 : 0
  secret      = google_secret_manager_secret.june_auth_fernet_key.id
  secret_data = var.june_auth_fernet_key
}

resource "google_secret_manager_secret_version" "june_auth_mfa_jwt_secret" {
  count       = var.june_auth_create_secret_versions && var.june_auth_mfa_jwt_secret != null ? 1 : 0
  secret      = google_secret_manager_secret.june_auth_mfa_jwt_secret.id
  secret_data = var.june_auth_mfa_jwt_secret
}

# Cloud Run service via shared module
module "june_auth" {
  source      = "./modules/cloud_run_service"
  project_id  = var.project_id
  region      = var.region
  service_name = var.june_auth_service_name
  image       = var.june_auth_image

  allow_unauthenticated = var.june_auth_allow_unauthenticated

  env = {
    GOOGLE_CLOUD_PROJECT   = var.project_id
    TOTP_ISSUER            = var.june_auth_totp_issuer
    TOTP_ALG               = var.june_auth_totp_alg
    TOTP_DIGITS            = tostring(var.june_auth_totp_digits)
    TOTP_PERIOD            = tostring(var.june_auth_totp_period)
    MFA_JWT_TTL_SECONDS    = tostring(var.june_auth_mfa_jwt_ttl_seconds)
  }

  secret_env = {
    FERNET_KEY = {
      secret  = google_secret_manager_secret.june_auth_fernet_key.id
      version = "latest"
    }
    MFA_JWT_SECRET = {
      secret  = google_secret_manager_secret.june_auth_mfa_jwt_secret.id
      version = "latest"
    }
  }
}
