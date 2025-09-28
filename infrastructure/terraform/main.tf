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
  name        = "june-tts-build"
  description = "Build june-tts and push to Artifact Registry + Docker Hub"

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^master$"
    }
  }

  filename = "June/services/june-tts/cloudbuild.yaml"

  depends_on = [
    google_project_service.cloudbuild,
    google_project_service.secretmanager,
    google_artifact_registry_repository.june
  ]
}

# Cloud Build Trigger for June-Orchestrator
resource "google_cloudbuild_trigger" "june_orchestrator_build" {
  name        = "june-orchestrator-build"
  description = "Build june-orchestrator and push to Artifact Registry + Docker Hub"

  github {
    owner = var.github_owner
    name  = var.github_repo
    push {
      branch = "^master$"
    }
  }

  filename = "June/services/june-orchestrator/cloudbuild.yaml"

  depends_on = [
    google_project_service.cloudbuild,
    google_project_service.secretmanager,
    google_artifact_registry_repository.june
  ]
}
