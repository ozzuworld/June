############################################
# june-auth: Secrets, APIs, Cloud Run
############################################

# Ensure commonly-used APIs are enabled
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

# Secrets for FERNET_KEY and MFA_JWT_SECRET
resource "google_secret_manager_secret" "june_auth_fernet_key" {
  project   = var.project_id
  secret_id = "${var.june_auth_service_name}-fernet"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "june_auth_fernet_key_v" {
  secret      = google_secret_manager_secret.june_auth_fernet_key.id
  secret_data = coalesce(var.june_auth_fernet_key, random_id.june_auth_fernet_key_hex.b64_url)
}

resource "google_secret_manager_secret" "june_auth_mfa_jwt_secret" {
  project   = var.project_id
  secret_id = "${var.june_auth_service_name}-mfa-jwt"
  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "june_auth_mfa_jwt_secret_v" {
  secret      = google_secret_manager_secret.june_auth_mfa_jwt_secret.id
  secret_data = coalesce(var.june_auth_mfa_jwt_secret, random_id.june_auth_mfa_jwt_key_hex.hex)
}

# Randoms if the user doesn't provide values (safe defaults)
resource "random_id" "june_auth_fernet_key_hex" {
  byte_length = 32
}

resource "random_id" "june_auth_mfa_jwt_key_hex" {
  byte_length = 32
}

# Deploy the service
module "june_auth" {
  source  = "./modules/cloud_run_service"
  project_id = var.project_id
  region     = var.region

  service_name         = var.june_auth_service_name
  image                = var.june_auth_image
  allow_unauthenticated = var.june_auth_allow_unauthenticated

  min_instances = var.june_auth_min_instances
  max_instances = var.june_auth_max_instances

  env = {
    # App-specific clear env (Firebase project ID used by the code)
    FIREBASE_PROJECT_ID = var.firebase_project_id
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


# Allow the service account to access Firestore (Native)
resource "google_project_iam_member" "june_auth_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${module.june_auth.service_account_email}"
}
