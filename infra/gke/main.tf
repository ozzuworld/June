# infra/gke/main.tf - Simplified working version
# Focus: Get GKE cluster running with basic services first

terraform {
  required_version = ">= 1.0"
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

# Variables
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

# Configure providers
provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_client_config" "default" {}

provider "kubernetes" {
  host                   = "https://${google_container_cluster.primary.endpoint}"
  token                  = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(google_container_cluster.primary.master_auth[0].cluster_ca_certificate)
}

# Enable required APIs
resource "google_project_service" "container" {
  project = var.project_id
  service = "container.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "compute" {
  project = var.project_id
  service = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifactregistry" {
  project = var.project_id
  service = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

# VPC Network
resource "google_compute_network" "vpc" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
  project                 = var.project_id
  
  depends_on = [google_project_service.compute]
}

# Subnet with secondary ranges for GKE
resource "google_compute_subnetwork" "subnet" {
  name          = "${var.cluster_name}-subnet"
  ip_cidr_range = "10.0.0.0/16"
  region        = var.region
  network       = google_compute_network.vpc.id
  project       = var.project_id

  private_ip_google_access = true

  secondary_ip_range {
    range_name    = "k8s-pods"
    ip_cidr_range = "10.4.0.0/14"
  }

  secondary_ip_range {
    range_name    = "k8s-services"
    ip_cidr_range = "10.8.0.0/20"
  }
}

# GKE Autopilot Cluster
resource "google_container_cluster" "primary" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id

  # Enable Autopilot
  enable_autopilot = true
  
  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.subnet.id

  ip_allocation_policy {
    cluster_secondary_range_name  = google_compute_subnetwork.subnet.secondary_ip_range[0].range_name
    services_secondary_range_name = google_compute_subnetwork.subnet.secondary_ip_range[1].range_name
  }

  # Workload Identity
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  depends_on = [
    google_project_service.container,
    google_project_service.compute,
  ]
}

# Artifact Registry
resource "google_artifact_registry_repository" "june_repo" {
  location      = var.region
  project       = var.project_id
  repository_id = "june"
  description   = "June AI Platform Docker repository"
  format        = "DOCKER"
  
  depends_on = [google_project_service.artifactregistry]
}

# Static IP for Load Balancer
resource "google_compute_global_address" "june_ip" {
  name    = "june-services-ip"
  project = var.project_id
}

# Create basic namespace
resource "kubernetes_namespace" "june_services" {
  metadata {
    name = "june-services"
    labels = {
      "managed-by" = "terraform"
    }
  }
  
  depends_on = [google_container_cluster.primary]
}

# Basic secret for API keys (populate manually after deployment)
resource "kubernetes_secret" "june_secrets" {
  metadata {
    name      = "june-secrets"
    namespace = kubernetes_namespace.june_services.metadata[0].name
  }

  data = {
    GEMINI_API_KEY     = ""  # Set after deployment
    CHATTERBOX_API_KEY = ""  # Set after deployment
  }

  type = "Opaque"
}

# Outputs
output "cluster_name" {
  description = "GKE cluster name"
  value       = google_container_cluster.primary.name
}

output "cluster_endpoint" {
  description = "GKE cluster endpoint"
  value       = google_container_cluster.primary.endpoint
  sensitive   = true
}

output "get_credentials_command" {
  description = "Command to configure kubectl"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.primary.name} --region=${var.region} --project=${var.project_id}"
}

output "artifact_registry_url" {
  description = "Artifact Registry URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/june"
}

output "static_ip" {
  description = "Static IP for ingress"
  value       = google_compute_global_address.june_ip.address
}

output "next_steps" {
  description = "Next steps to complete deployment"
  value = <<-EOT
    1. Configure kubectl: ${google_container_cluster.primary.name}
    2. Build and push images to: ${var.region}-docker.pkg.dev/${var.project_id}/june
    3. Update API keys: kubectl patch secret june-secrets -n june-services --patch='{"data":{"GEMINI_API_KEY":"<base64-key>"}}'
    4. Deploy services: kubectl apply -f k8s/june-services/
    5. Static IP for DNS: ${google_compute_global_address.june_ip.address}
  EOT
}