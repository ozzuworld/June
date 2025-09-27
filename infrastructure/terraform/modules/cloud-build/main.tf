# Cloud Build Module - Production Ready
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# Enable Cloud Build API
resource "google_project_service" "cloudbuild" {
  service = "cloudbuild.googleapis.com"
  project = var.project_id

  disable_on_destroy = false
}

resource "google_project_service" "secretmanager" {
  service = "secretmanager.googleapis.com"
  project = var.project_id

  disable_on_destroy = false
}

# Get current project data
data "google_project" "current" {
  project_id = var.project_id
}

# Cloud Build service account permissions
resource "google_project_iam_member" "cloudbuild_artifactregistry" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"

  depends_on = [google_project_service.cloudbuild]
}

resource "google_project_iam_member" "cloudbuild_storage" {
  project = var.project_id
  role    = "roles/storage.admin"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"

  depends_on = [google_project_service.cloudbuild]
}

# Create Cloud Build configuration files for manual builds
resource "local_file" "build_configs" {
  for_each = var.services

  filename = "${path.root}/build-configs/${each.key}-cloudbuild.yaml"
  content = templatefile("${path.module}/templates/cloudbuild.yaml.tpl", {
    service_name  = each.value.name
    service_key   = each.key
    region        = var.region
    project_id    = var.project_id
    build_timeout = each.value.build_timeout
    machine_type  = each.value.machine_type
    disk_size     = each.value.disk_size
    environment   = var.environment
  })
}
