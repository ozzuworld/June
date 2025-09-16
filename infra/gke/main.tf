# infra/gke/main.tf - UNIFIED GKE AUTOPILOT DEPLOYMENT
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
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
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

variable "harbor_domain" {
  description = "Harbor domain (optional)"
  type        = string
  default     = ""
}

# Enable required APIs
resource "google_project_service" "required_apis" {
  for_each = toset([
    "container.googleapis.com",
    "compute.googleapis.com",
    "storage.googleapis.com",
    "secretmanager.googleapis.com",
    "sql.googleapis.com",
    "redis.googleapis.com",
    "monitoring.googleapis.com",
    "logging.googleapis.com"
  ])
  
  project = var.project_id
  service = each.value
  
  disable_on_destroy = false
}

# GKE Autopilot Cluster - UNIFIED for Harbor + June Services
resource "google_container_cluster" "unified_cluster" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id

  # Enable Autopilot - Google manages nodes completely
  enable_autopilot = true
  
  # Network configuration
  network    = "default"
  subnetwork = "default"
  
  # IP allocation for pods and services  
  ip_allocation_policy {
    cluster_secondary_range_name  = "gke-pods"
    services_secondary_range_name = "gke-services"
  }
  
  # Security
  enable_shielded_nodes = true
  
  # Workload Identity for secure service account access
  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
  
  # Private cluster for security
  private_cluster_config {
    enable_private_nodes    = true
    enable_private_endpoint = false
    master_ipv4_cidr_block  = "172.16.0.0/28"
    
    master_global_access_config {
      enabled = true
    }
  }
  
  # Monitoring and logging
  monitoring_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
    
    managed_prometheus {
      enabled = true
    }
  }
  
  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  # Resource labels
  resource_labels = {
    purpose = "june-unified"
    team    = "june-dev"
  }

  depends_on = [google_project_service.required_apis]
}

# Service Accounts
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

# Grant necessary permissions
resource "google_project_iam_member" "workload_permissions" {
  for_each = {
    # Harbor needs storage and secret access
    "harbor-storage" = {
      sa   = "harbor"
      role = "roles/storage.admin"
    }
    "harbor-secrets" = {
      sa   = "harbor"
      role = "roles/secretmanager.secretAccessor"
    }
    
    # All services need basic monitoring
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
    
    # Secret access for app configs
    "orchestrator-secrets" = {
      sa   = "june-orchestrator"
      role = "roles/secretmanager.secretAccessor" 
    }
    "stt-secrets" = {
      sa   = "june-stt"
      role = "roles/secretmanager.secretAccessor"
    }
    "tts-secrets" = {
      sa   = "june-tts"
      role = "roles/secretmanager.secretAccessor"
    }
    "idp-secrets" = {
      sa   = "june-idp"
      role = "roles/secretmanager.secretAccessor"
    }
  }
  
  project = var.project_id
  role    = each.value.role
  member  = "serviceAccount:${google_service_account.workload_identity[each.value.sa].email}"
}

# Workload Identity bindings
resource "google_service_account_iam_member" "workload_identity_binding" {
  for_each = toset([
    "harbor",
    "june-orchestrator",
    "june-stt", 
    "june-tts",
    "june-idp"
  ])
  
  service_account_id = google_service_account.workload_identity[each.key].name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[${each.key}/${each.key}]"
}

# Storage for Harbor registry
resource "google_storage_bucket" "harbor_registry" {
  name     = "${var.project_id}-harbor-registry"
  location = var.region
  project  = var.project_id

  uniform_bucket_level_access = true
  
  versioning {
    enabled = true
  }
  
  lifecycle_rule {
    action {
      type = "Delete"
    }
    condition {
      age = 90
    }
  }
}

# PostgreSQL for Harbor (shared database)
resource "google_sql_database_instance" "harbor_postgres" {
  name             = "${var.cluster_name}-postgres"
  database_version = "POSTGRES_15"
  region           = var.region
  project          = var.project_id

  settings {
    tier              = "db-f1-micro"  # Free tier eligible
    availability_type = "ZONAL"       # Single zone for cost
    disk_size         = 20            # Minimum size
    disk_type         = "PD_SSD"

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      location                       = var.region
      point_in_time_recovery_enabled = false  # Disable for cost
    }

    ip_configuration {
      ipv4_enabled       = true
      private_network    = "default"
      require_ssl        = false
      authorized_networks {
        name  = "allow-gke"
        value = "0.0.0.0/0"  # Restrict in production
      }
    }
  }

  deletion_protection = false  # Allow deletion for dev
}

# Databases
resource "google_sql_database" "databases" {
  for_each = toset([
    "harbor",
    "june_orchestrator", 
    "june_idp"
  ])
  
  name     = each.key
  instance = google_sql_database_instance.harbor_postgres.name
  project  = var.project_id
}

# Database users
resource "google_sql_user" "db_users" {
  for_each = toset([
    "harbor",
    "june_orchestrator",
    "june_idp"
  ])
  
  name     = each.key
  instance = google_sql_database_instance.harbor_postgres.name
  password = random_password.db_passwords[each.key].result
  project  = var.project_id
}

resource "random_password" "db_passwords" {
  for_each = toset([
    "harbor",
    "june_orchestrator", 
    "june_idp"
  ])
  
  length  = 24
  special = true
}

# Store passwords in Secret Manager
resource "google_secret_manager_secret" "db_passwords" {
  for_each = toset([
    "harbor",
    "june_orchestrator",
    "june_idp"
  ])
  
  secret_id = "${each.key}-db-password"
  project   = var.project_id

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_passwords" {
  for_each = toset([
    "harbor",
    "june_orchestrator",
    "june_idp"
  ])
  
  secret      = google_secret_manager_secret.db_passwords[each.key].name
  secret_data = random_password.db_passwords[each.key].result
}

# Redis for Harbor and caching
resource "google_redis_instance" "shared_redis" {
  name           = "${var.cluster_name}-redis"
  tier           = "BASIC"      # Single node for cost
  memory_size_gb = 1
  project        = var.project_id
  region         = var.region

  auth_enabled   = true
  redis_version  = "REDIS_6_X"
  
  display_name = "June Shared Redis"
}

# Kubernetes provider
data "google_client_config" "provider" {}

provider "kubernetes" {
  host  = "https://${google_container_cluster.unified_cluster.endpoint}"
  token = data.google_client_config.provider.access_token
  cluster_ca_certificate = base64decode(
    google_container_cluster.unified_cluster.master_auth[0].cluster_ca_certificate,
  )
}

provider "helm" {
  kubernetes {
    host  = "https://${google_container_cluster.unified_cluster.endpoint}"
    token = data.google_client_config.provider.access_token
    cluster_ca_certificate = base64decode(
      google_container_cluster.unified_cluster.master_auth[0].cluster_ca_certificate,
    )
  }
}

# Create namespaces
resource "kubernetes_namespace" "namespaces" {
  for_each = toset([
    "harbor",
    "june-services",
    "monitoring"
  ])
  
  metadata {
    name = each.key
    labels = {
      managed-by = "terraform"
    }
  }
  
  depends_on = [google_container_cluster.unified_cluster]
}

# Service accounts with Workload Identity
resource "kubernetes_service_account" "workload_identity_sa" {
  for_each = {
    "harbor"             = "harbor"
    "june-orchestrator"  = "june-services" 
    "june-stt"          = "june-services"
    "june-tts"          = "june-services"
    "june-idp"          = "june-services"
  }
  
  metadata {
    name      = each.key
    namespace = each.value
    annotations = {
      "iam.gke.io/gcp-service-account" = google_service_account.workload_identity[each.key].email
    }
  }
  
  depends_on = [kubernetes_namespace.namespaces]
}

# Outputs
output "cluster_name" {
  value = google_container_cluster.unified_cluster.name
}

output "cluster_endpoint" {
  value = google_container_cluster.unified_cluster.endpoint
  sensitive = true
}

output "cluster_ca_certificate" {
  value = google_container_cluster.unified_cluster.master_auth[0].cluster_ca_certificate
  sensitive = true
}

output "get_credentials_command" {
  value = "gcloud container clusters get-credentials ${google_container_cluster.unified_cluster.name} --region=${var.region} --project=${var.project_id}"
}

output "postgres_connection_name" {
  value = google_sql_database_instance.harbor_postgres.connection_name
}

output "redis_host" {
  value = google_redis_instance.shared_redis.host
}

output "harbor_registry_bucket" {
  value = google_storage_bucket.harbor_registry.name
}