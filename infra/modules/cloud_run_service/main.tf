resource "google_cloud_run_v2_service" "this" {
  name     = var.service_name
  location = var.region

  template {
    # optional SA override
    service_account = var.service_account

    containers {
      image = var.image
      args  = var.args

      ports { container_port = var.port }

      # plain env
      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      # secret-backed env
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

    # Sticky sessions helpful for Keycloak
    session_affinity = var.session_affinity
  }

  # traffic/ingress/labels blocks here if you already have them
}
