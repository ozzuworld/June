resource "google_cloud_run_v2_service" "this" {
  name     = var.service_name
  location = var.region

  template {
    service_account = var.service_account

    containers {
      image = var.image
      args  = var.args

      ports { container_port = var.port }

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.env_secrets
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

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }
    }

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    session_affinity = var.session_affinity
  }
}
