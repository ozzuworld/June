resource "google_cloudbuild_trigger" "service_builds" {
  for_each = var.services

  name         = "${each.key}-build-and-push"
  description  = "Build ${each.key} and push to Artifact Registry + Docker Hub"
  project      = var.project_id

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^master$"
    }
  }

  included_files = ["June/services/${each.key}/**"]

  build {
    timeout = each.key == "june-tts" ? "7200s" : "3600s"

    options {
      machine_type = each.key == "june-tts" ? "E2_HIGHCPU_32" : "E2_HIGHCPU_8"
      disk_size_gb = each.key == "june-tts" ? 200 : 100
      logging      = "CLOUD_LOGGING_ONLY"
    }

    step {
      name = "gcr.io/cloud-builders/gcloud"
      args = [
        "builds", "submit",
        "--config=cloudbuild.yaml",
        "."
      ]
      dir     = "June/services/${each.key}"
      timeout = each.key == "june-tts" ? "7200s" : "3600s"
    }
  }

  depends_on = [
    google_project_service.cloudbuild,
    google_project_service.secretmanager
  ]
}
