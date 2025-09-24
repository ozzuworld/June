# infra/gke/main.tf - Updated with auto-deployment
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
resource "google_project_service" "required_apis" {
  for_each = toset([
    "container.googleapis.com",
    "compute.googleapis.com", 
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "dns.googleapis.com"
  ])
  
  project = var.project_id
  service = each.value
  disable_on_destroy = false
}

# VPC Network  
resource "google_compute_network" "vpc" {
  name                    = "${var.cluster_name}-vpc"
  auto_create_subnetworks = false
  project                 = var.project_id
  
  depends_on = [google_project_service.required_apis]
}

# Subnet
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

  enable_autopilot = true
  
  network    = google_compute_network.vpc.id
  subnetwork = google_compute_subnetwork.subnet.id

  ip_allocation_policy {
    cluster_secondary_range_name  = google_compute_subnetwork.subnet.secondary_ip_range[0].range_name
    services_secondary_range_name = google_compute_subnetwork.subnet.secondary_ip_range[1].range_name
  }

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  depends_on = [google_project_service.required_apis]
}

# Artifact Registry
resource "google_artifact_registry_repository" "june_repo" {
  location      = var.region
  project       = var.project_id  
  repository_id = "june"
  description   = "June AI Platform Docker repository"
  format        = "DOCKER"
  
  depends_on = [google_project_service.required_apis]
}

# Static IP for Load Balancer
resource "google_compute_global_address" "june_ip" {
  name    = "june-services-ip"
  project = var.project_id
}

# Secret Manager secrets
resource "google_secret_manager_secret" "june_secrets" {
  for_each = toset([
    "keycloak-admin-password",
    "jwt-signing-key",
    "database-password", 
    "orchestrator-client-secret",
    "stt-client-secret"
  ])

  secret_id = each.key
  project   = var.project_id

  replication {
    auto {}
  }
  
  depends_on = [google_project_service.required_apis]
}

# Service Account for Secret Manager
resource "google_service_account" "june_secret_manager" {
  account_id   = "june-secret-manager"
  display_name = "June Secret Manager Service Account"
  project      = var.project_id
}

# IAM for Secret Manager access
resource "google_project_iam_member" "june_secret_accessor" {
  project = var.project_id
  role    = "roles/secretmanager.secretAccessor"
  member  = "serviceAccount:${google_service_account.june_secret_manager.email}"
}

# Kubernetes namespace
resource "kubernetes_namespace" "june_services" {
  metadata {
    name = "june-services"
    labels = {
      "managed-by" = "terraform"
    }
  }
  
  depends_on = [google_container_cluster.primary]
}

# Kubernetes service account with Workload Identity
resource "kubernetes_service_account" "june_secret_manager" {
  metadata {
    name      = "june-secret-manager"
    namespace = kubernetes_namespace.june_services.metadata[0].name
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.june_secret_manager.email
    }
  }
}

# Workload Identity binding
resource "google_service_account_iam_member" "june_workload_identity" {
  service_account_id = google_service_account.june_secret_manager.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${kubernetes_namespace.june_services.metadata[0].name}/june-secret-manager]"
}

# Resource quota for free tier compliance
resource "kubernetes_resource_quota" "june_quota" {
  metadata {
    name      = "june-resource-quota"
    namespace = kubernetes_namespace.june_services.metadata[0].name
  }
  
  spec {
    hard = {
      "requests.cpu"    = "6"
      "requests.memory" = "24Gi"
      "limits.cpu"      = "8" 
      "limits.memory"   = "30Gi"
      "persistentvolumeclaims" = "5"
      "services.loadbalancers" = "0"
    }
  }
}

# Limit ranges
resource "kubernetes_limit_range" "june_limits" {
  metadata {
    name      = "june-limit-range"
    namespace = kubernetes_namespace.june_services.metadata[0].name
  }
  
  spec {
    limit {
      type = "Container"
      default = {
        cpu    = "500m"
        memory = "512Mi"
      }
      default_request = {
        cpu    = "200m" 
        memory = "256Mi"
      }
      max = {
        cpu    = "1"
        memory = "1Gi"  
      }
      min = {
        cpu    = "100m"
        memory = "128Mi"
      }
    }
  }
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
  description = "Static IP for DNS configuration"  
  value       = google_compute_global_address.june_ip.address
}

output "dns_configuration" {
  description = "Required DNS A records"
  value = {
    "allsafe.world"     = google_compute_global_address.june_ip.address
    "api.allsafe.world" = google_compute_global_address.june_ip.address  
    "stt.allsafe.world" = google_compute_global_address.june_ip.address
    "idp.allsafe.world" = google_compute_global_address.june_ip.address
  }
}