resource "google_service_account" "sa" {
  project      = var.project_id
  account_id   = "${var.service_name}-sa"
  display_name = "${var.service_name} runner"
}

resource "google_cloud_run_v2_service" "svc" {
  name     = var.service_name
  project  = var.project_id
  location = var.region

  template {
    service_account = google_service_account.sa.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      resources {
        cpu_idle = true
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      # Plain env vars
      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Secret-sourced env vars
      dynamic "env" {
        for_each = var.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }
    }
  }

  ingress = "INGRESS_TRAFFIC_ALL"
}

# Public access (if desired)
resource "google_cloud_run_service_iam_member" "public" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  service  = google_cloud_run_v2_service.svc.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Allow reading secrets only when used
resource "google_project_iam_member" "secret_access" {
  count   = length(var.secret_env) > 0 ? 1 : 0
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.sa.email}"
}
