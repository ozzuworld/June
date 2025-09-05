module "auth" {
  source       = "./modules/cloud_run_service"
  project_id   = var.project_id
  region       = var.region
  service_name = "keycloak"
  image        = "quay.io/keycloak/keycloak:24.0"

  allow_unauthenticated = true # needed for browser login pages
  min_instances         = 1
  max_instances         = 5
  cpu                   = 2
  memory                = "2Gi"
  ingress               = "INGRESS_TRAFFIC_ALL"

  # Private egress to reach the VM's internal IP
  vpc_connector = google_vpc_access_connector.serverless.id
  vpc_egress    = "PRIVATE_RANGES_ONLY"

  env = {
    KC_BOOTSTRAP_ADMIN_USERNAME = "admin"
    KC_DB                       = "postgres"
    KC_DB_URL                   = local.kc_db_url
    KC_DB_USERNAME              = var.kc_db_user

    KC_HOSTNAME        = local.kc_hostname
    KC_PROXY           = "edge"
    KC_HEALTH_ENABLED  = "true"
    KC_METRICS_ENABLED = "true"
  }

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

  # Ensure DB & firewall are ready first
  depends_on = [
    module.db_vm,
    google_compute_firewall.allow_pg_internal
  ]
}

# Optional custom domain
resource "google_cloud_run_domain_mapping" "auth" {
  location = var.region
  name     = local.kc_hostname
  metadata { namespace = var.project_id }
  spec { route_name = module.auth.service_name }
}
