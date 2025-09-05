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
    # Request timeout for each request
    timeout = "300s"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    labels = {
      "managed-by" = "terraform"
    }

    annotations = {
      "run.googleapis.com/ingress" = "all"
    }

    containers {
      image = var.image

      # Explicit container port (Cloud Run still injects $PORT)
      ports {
        container_port = 8080
      }

      # Environment variables (plain)
      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Environment variables from Secret Manager
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
}

# Allow unauthenticated if requested
resource "google_cloud_run_v2_service_iam_member" "invoker" {
  count    = var.allow_unauthenticated ? 1 : 0
  project  = var.project_id
  location = var.region
  service  = google_cloud_run_v2_service.svc.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Allow the service to access only the specified secrets
resource "google_secret_manager_secret_iam_member" "secret_access" {
  for_each = var.secret_env
  secret_id = each.value.secret
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.sa.email}"
}
