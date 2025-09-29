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

resource "google_project_service" "container" {
  service = "container.googleapis.com"
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

# GKE Cluster
resource "google_container_cluster" "june_cluster" {
  name     = var.cluster_name
  location = var.region
  
  # We can't create a cluster with no node pool defined, but we want to only use
  # separately managed node pools. So we create the smallest possible default
  # node pool and immediately delete it.
  remove_default_node_pool = true
  initial_node_count       = 1
  
  # Basic cluster settings
  deletion_protection = false
  
  # Network configuration
  network    = "default"
  subnetwork = "default"
  
  # Addons
  addons_config {
    http_load_balancing {
      disabled = false
    }
    horizontal_pod_autoscaling {
      disabled = false
    }
  }
  
  # Master auth networks - allow access from anywhere for now
  master_authorized_networks_config {
    cidr_blocks {
      cidr_block   = "0.0.0.0/0"
      display_name = "All networks"
    }
  }
  
  depends_on = [
    google_project_service.container,
    google_project_service.cloudbuild
  ]
}

# Separately Managed Node Pool
resource "google_container_node_pool" "june_nodes" {
  name       = "june-node-pool"
  location   = var.region
  cluster    = google_container_cluster.june_cluster.name
  node_count = 1

  node_config {
    preemptible  = true
    machine_type = "e2-medium"
    disk_size_gb = 20
    disk_type    = "pd-standard"
    
    # OAuth scopes
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform"
    ]
    
    # Labels
    labels = local.common_labels
    
    # Metadata
    metadata = {
      disable-legacy-endpoints = "true"
    }
  }
  
  # Management
  management {
    auto_repair  = true
    auto_upgrade = true
  }
  
  # Autoscaling
  autoscaling {
    min_node_count = 1
    max_node_count = 3
  }
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
