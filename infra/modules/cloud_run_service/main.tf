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

  # Ensure secret IAM (if any) is applied before creating the service
  depends_on = [
    google_secret_manager_secret_iam_member.secret_access
  ]
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

# Allow reading specific secrets only when used (least privilege)
resource "google_secret_manager_secret_iam_member" "secret_access" {
  for_each = var.secret_env
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sa.email}"
}
