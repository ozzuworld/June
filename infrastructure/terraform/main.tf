terraform {
  required_version = ">= 1.0"
  
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Enable required APIs
resource "google_project_service" "artifact_registry" {
  service = "artifactregistry.googleapis.com"
}

resource "google_project_service" "cloudbuild" {
  service = "cloudbuild.googleapis.com"
}

resource "google_project_service" "secretmanager" {
  service = "secretmanager.googleapis.com"
}

# Local values
locals {
  common_labels = {
    project     = "june-ai-platform"
    environment = var.environment
    managed_by  = "terraform"
  }
}

# Create Artifact Registry Repository
resource "google_artifact_registry_repository" "june" {
  location      = var.region
  repository_id = "june"
  description   = "June AI Platform Docker Images"
  format        = "DOCKER"

  labels = local.common_labels
}

# Get current project info
data "google_project" "current" {
  project_id = var.project_id
}

# Grant Cloud Build access to Artifact Registry
resource "google_project_iam_member" "cloudbuild_artifactregistry" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

# Cloud Build Trigger for June-TTS
resource "google_cloudbuild_trigger" "june_tts_build" {
  name        = "june-tts-build-and-push"
  description = "Build june-tts and push to Artifact Registry + Docker Hub"

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^master$"
    }
  }

  included_files = ["June/services/june-tts/**"]

  build {
    timeout = "7200s"

    options {
      machine_type = "E2_HIGHCPU_32"
      disk_size_gb = 200
      logging      = "CLOUD_LOGGING_ONLY"
    }

    step {
      name = "gcr.io/cloud-builders/gcloud"
      args = [
        "builds", "submit",
        "--config=cloudbuild.yaml",
        "."
      ]
      dir     = "June/services/june-tts"
      timeout = "7200s"
    }
  }

  depends_on = [
    google_project_service.cloudbuild,
    google_project_service.secretmanager,
    google_artifact_registry_repository.june
  ]
}

# Cloud Build Trigger for June-Orchestrator
resource "google_cloudbuild_trigger" "june_orchestrator_build" {
  name        = "june-orchestrator-build-and-push"
  description = "Build june-orchestrator and push to Artifact Registry + Docker Hub"

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^master$"
    }
  }

  included_files = ["June/services/june-orchestrator/**"]

  build {
    timeout = "3600s"

    options {
      machine_type = "E2_HIGHCPU_8"
      disk_size_gb = 100
      logging      = "CLOUD_LOGGING_ONLY"
    }

    step {
      name = "gcr.io/cloud-builders/gcloud"
      args = [
        "builds", "submit",
        "--config=cloudbuild.yaml",
        "."
      ]
      dir     = "June/services/june-orchestrator"
      timeout = "3600s"
    }
  }

  depends_on = [
    google_project_service.cloudbuild,
    google_project_service.secretmanager,
    google_artifact_registry_repository.june
  ]
}
