terraform {
  required_version = ">= 1.6.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38"
    }
  }
}

resource "google_service_account" "sa" {
  account_id   = var.service_name
  display_name = "${var.service_name} runtime"
}

resource "google_cloud_run_v2_service" "svc" {
  name     = var.service_name
  location = var.region
  ingress  = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.sa.email

    containers {
      image = var.image
      args  = var.args
      env   = [
        for k, v in var.env : {
          name  = k
          value = v
        }
      ]
      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }
      ports { container_port = var.port }
    }

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }
  }
}

resource "google_cloud_run_v2_service_iam_member" "invoker_all" {
  location = google_cloud_run_v2_service.svc.location
  name     = google_cloud_run_v2_service.svc.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "url" { value = google_cloud_run_v2_service.svc.uri }
