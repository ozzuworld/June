# Cloud Build for June AI Platform
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

# Enable APIs
resource "google_project_service" "cloudbuild" {
  service = "cloudbuild.googleapis.com"
  project = var.project_id
}

resource "google_project_service" "secretmanager" {
  service = "secretmanager.googleapis.com"
  project = var.project_id
}

# Service account permissions
data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_iam_member" "cloudbuild_artifactregistry" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

# Build triggers for services
resource "google_cloudbuild_trigger" "service_builds" {
  for_each = var.services
  
  name        = "${each.value.name}-build"
  description = "Build ${each.value.name} on changes"
  
  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^master$"
    }
  }
  
  included_files = ["June/services/${each.key}/**"]
  
  build {
    step {
      name = "gcr.io/cloud-builders/docker"
      args = [
        "build",
        "-t", "${var.region}-docker.pkg.dev/${var.project_id}/june/${each.value.name}:$SHORT_SHA",
        "-t", "${var.region}-docker.pkg.dev/${var.project_id}/june/${each.value.name}:latest",
        "-f", "June/services/${each.key}/Dockerfile",
        "June/services/${each.key}"
      ]
      timeout = each.key == "june-tts" ? "3600s" : "1800s"
    }
    
    step {
      name = "gcr.io/cloud-builders/docker"
      args = [
        "push",
        "${var.region}-docker.pkg.dev/${var.project_id}/june/${each.value.name}:$SHORT_SHA"
      ]
    }
    
    step {
      name = "gcr.io/cloud-builders/docker"
      args = [
        "push",
        "${var.region}-docker.pkg.dev/${var.project_id}/june/${each.value.name}:latest"
      ]
    }
    
    options {
      machine_type = each.key == "june-tts" ? "E2_HIGHCPU_8" : "E2_HIGHCPU_32"
      disk_size_gb = each.key == "june-tts" ? 100 : 50
      logging      = "CLOUD_LOGGING_ONLY"
    }
    
    timeout = each.key == "june-tts" ? "4800s" : "2400s"
    
    tags = [each.value.name, "$SHORT_SHA", "$BRANCH_NAME", var.environment]
  }
}
