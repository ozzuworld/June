# infra/gke/main.tf - SIMPLIFIED for Oracle Backend
# Removed all PostgreSQL/Redis complexity

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.23"
    }
  }
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
  default     = "us-central1"
}

variable "cluster_name" {
  description = "GKE cluster name"
  type        = string
  default     = "june-unified-cluster"
}

# Enable required APIs (minimal set)
resource "google_project_service" "apis" {
  for_each = toset([
    "container.googleapis.com",
    "compute.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com"
  ])
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

# VPC and Subnet for GKE
resource "google_compute_network" "main" {
  name                    = "${var.cluster_name}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "main" {
  name                     = "${var.cluster_name}-subnet"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.main.id
  ip_cidr_range            = "10.0.0.0/16"
  private_ip_google_access = true

  # Secondary ranges for GKE pods and services
  secondary_ip_range {
    range_name    = "${var.cluster_name}-pods"
    ip_cidr_range = "10.4.0.0/14"
  }

  secondary_ip_range {
    range_name    = "${var.cluster_name}-services"
    ip_cidr_range = "10.8.0.0/20"
  }
}

# GKE Autopilot Cluster - Clean and Simple
resource "google_container_cluster" "cluster" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id

  enable_autopilot = true

  network    = google_compute_network.main.id
  subnetwork = google_compute_subnetwork.main.name

  ip_allocation_policy {
    cluster_secondary_range_name  = google_compute_subnetwork.main.secondary_ip_range[0].range_name
    services_secondary_range_name = google_compute_subnetwork.main.secondary_ip_range[1].range_name
  }

  # Workload Identity for secure service account access
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  depends_on = [google_project_service.apis]
}

# Artifact Registry for container images
resource "google_artifact_registry_repository" "june_repo" {
  location      = var.region
  project       = var.project_id
  repository_id = "june"
  description   = "June AI Platform container registry"
  format        = "DOCKER"

  labels = {
    purpose = "june-platform"
  }
}

# Service accounts for workload identity
resource "google_service_account" "workload_identity" {
  for_each = toset([
    "harbor",
    "june-orchestrator",
    "june-stt", 
    "june-tts",
    "june-idp"
  ])
  
  account_id   = "${each.key}-gke"
  display_name = "${each.key} GKE Service Account"
  project      = var.project_id
}

# Basic IAM permissions
resource "google_project_iam_member" "workload_permissions" {
  for_each = {
    "harbor-storage" = {
      sa   = "harbor"
      role = "roles/storage.admin"
    }
    "orchestrator-monitoring" = {
      sa   = "june-orchestrator"
      role = "roles/monitoring.metricWriter"
    }
    "stt-monitoring" = {
      sa   = "june-stt"
      role = "roles/monitoring.metricWriter"
    }
    "tts-monitoring" = {
      sa   = "june-tts"
      role = "roles/monitoring.metricWriter"
    }
    "idp-monitoring" = {
      sa   = "june-idp"
      role = "roles/monitoring.metricWriter"
    }
  }
  
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload_identity[each.value.sa].email}"
}

# Global static IP for ingress
resource "google_compute_global_address" "june_ip" {
  name    = "june-services-ip"
  project = var.project_id
}

# Storage bucket for Harbor registry storage
resource "google_storage_bucket" "harbor_registry" {
  name     = "${var.project_id}-harbor-registry"
  location = var.region
  project  = var.project_id

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  
  versioning {
    enabled = true
  }
  
  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

# Outputs
output "cluster_name" {
  value = google_container_cluster.cluster.name
}

output "cluster_endpoint" {
  value     = google_container_cluster.cluster.endpoint
  sensitive = true
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.cluster.name} --region=${var.region} --project=${var.project_id}"
}

output "artifact_registry_url" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/june"
}

output "static_ip" {
  value = google_compute_global_address.june_ip.address
}

output "harbor_bucket" {
  value = google_storage_bucket.harbor_registry.name
}

output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}