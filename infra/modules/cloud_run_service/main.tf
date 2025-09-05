#############################################
# Module: cloud_run_service
# File:   June/infra/modules/cloud_run_service/main.tf
#############################################

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

    # OPTIONAL: let callers pass Cloud Run annotations (e.g., Cloud SQL connector)
    # Only works if you also add `variable "annotations"` in variables.tf (see section 2).
    annotations = var.annotations

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

  # Ingress policy (public/private)
  ingress = var.ingress
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

output "service_name" {
  value = google_cloud_run_v2_service.svc.name
}

output "service_uri" {
  value = google_cloud_run_v2_service.svc.uri
}
