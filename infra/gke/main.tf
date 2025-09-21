# infra/gke/main.tf - FIXED: No Harbor, Oracle backend only
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

# Enable required APIs (minimal set for Oracle backend)
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
  ip_cidr_range            = "192.168.0.0/16"
  private_ip_google_access = true

  # Secondary ranges for GKE pods and services
  secondary_ip_range {
    range_name    = "${var.cluster_name}-pods"
    ip_cidr_range = "172.16.0.0/14"
  }

  secondary_ip_range {
    range_name    = "${var.cluster_name}-services"
    ip_cidr_range = "172.20.0.0/20"
  }
}

# GKE Autopilot Cluster - Oracle Backend Ready
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

# Artifact Registry for container images (handle existing)
resource "google_artifact_registry_repository" "june_repo" {
  count         = 1
  location      = var.region
  project       = var.project_id
  repository_id = "june"
  description   = "June AI Platform container registry"
  format        = "DOCKER"

  labels = {
    purpose = "june-platform"
  }

  lifecycle {
    ignore_changes = [labels, description]
  }
}

# Service accounts for workload identity (June services only)
resource "google_service_account" "workload_identity" {
  for_each = toset([
    "june-orchestrator",
    "june-stt", 
    "june-tts",
    "june-idp"
  ])
  
  account_id   = "${each.key}-gke"
  display_name = "${each.key} GKE Service Account"
  project      = var.project_id
}

# IAM permissions for service accounts (no Harbor)
resource "google_project_iam_member" "workload_permissions" {
  for_each = {
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
    # Secret Manager access for Oracle wallet and credentials
    "idp-secrets" = {
      sa   = "june-idp"
      role = "roles/secretmanager.secretAccessor"
    }
  }
  
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload_identity[each.value.sa].email}"
}

# Workload Identity bindings (no Harbor)
resource "google_service_account_iam_member" "workload_identity_binding" {
  for_each = toset([
    "june-orchestrator",
    "june-stt", 
    "june-tts",
    "june-idp"
  ])
  
  service_account_id = google_service_account.workload_identity[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[june-services/${each.key}]"
}

# Global static IP for ingress
resource "google_compute_global_address" "june_ip" {
  name    = "june-services-ip"
  project = var.project_id
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

output "project_id" {
  value = var.project_id
}

output "region" {
  value = var.region
}

output "service_accounts" {
  description = "GCP service account emails for workload identity"
  value = {
    for k, v in google_service_account.workload_identity : k => v.email
  }
}