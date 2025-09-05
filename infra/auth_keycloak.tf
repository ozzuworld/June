# Keycloak on Cloud Run using your existing module
module "auth" {
  source      = "./modules/cloud_run_service"
  project_id  = var.project_id
  region      = var.region
  service_name = "keycloak"

  image  = "quay.io/keycloak/keycloak:${var.kc_version}"

  # Auth UI must be reachable publicly (browser redirects). Keep this true.
  allow_unauthenticated = true

  min_instances = var.kc_min_instances
  max_instances = var.kc_max_instances

  # Reasonable defaults; your module already references these vars
  cpu    = 2
  memory = "2Gi"

  # Use env (official flags can be given as env, e.g. KC_PROXY=edge)
  env = {
    # Bootstrap admin (username is fine as plain env; password via Secret below)
    KC_BOOTSTRAP_ADMIN_USERNAME = "admin"

    # DB connection (external Postgres)
    KC_DB      = "postgres"
    KC_DB_URL  = local.kc_db_url
    KC_DB_USERNAME = var.kc_db_user
    # KC_DB_PASSWORD comes from Secret below

    # Runtime options aligned with official docs
    KC_HOSTNAME       = local.kc_hostname
    KC_PROXY          = "edge"
    KC_HEALTH_ENABLED = "true"
    KC_METRICS_ENABLED = "true"
  }

  # Inject sensitive values from Secret Manager
  secret_env = {
    KC_BOOTSTRAP_ADMIN_PASSWORD = {
      secret  = google_secret_manager_secret.kc_admin_password.id
      version = google_secret_manager_secret_version.kc_admin_password_v.version
    }
    KC_DB_PASSWORD = {
      secret  = google_secret_manager_secret.kc_db_password.id
      version = google_secret_manager_secret_version.kc_db_password_v.version
    }
  }
}

# Custom domain for auth (requires domain verification in Cloud Run)
resource "google_cloud_run_domain_mapping" "auth" {
  location = var.region
  name     = local.kc_hostname

  metadata {
    namespace = var.project_id
  }

  spec {
    route_name = "keycloak" # matches module.auth service_name
  }

  depends_on = [module.auth]
}

output "keycloak_url" {
  value = "https://${local.kc_hostname}"
}
