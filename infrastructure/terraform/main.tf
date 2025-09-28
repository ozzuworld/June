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
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.11"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Get existing GKE cluster information
data "google_container_cluster" "june_cluster" {
  name     = var.cluster_name
  location = var.region
  project  = var.project_id
}

data "google_client_config" "default" {}

# Configure Kubernetes provider
provider "kubernetes" {
  host  = "https://${data.google_container_cluster.june_cluster.endpoint}"
  token = data.google_client_config.default.access_token
  cluster_ca_certificate = base64decode(
    data.google_container_cluster.june_cluster.master_auth[0].cluster_ca_certificate
  )
}

# Configure Helm provider
provider "helm" {
  kubernetes {
    host  = "https://${data.google_container_cluster.june_cluster.endpoint}"
    token = data.google_client_config.default.access_token
    cluster_ca_certificate = base64decode(
      data.google_container_cluster.june_cluster.master_auth[0].cluster_ca_certificate
    )
  }
}

# Local values
locals {
  common_labels = {
    project     = "june-ai-platform"
    environment = var.environment
    managed_by  = "terraform"
  }
  
  services = {
    june-tts = {
      name          = "june-tts"
      port          = 8000
      path          = "/tts/*"
      build_timeout = "4800s"
      machine_type  = "E2_HIGHCPU_8"
      disk_size     = 100
    }
    june-orchestrator = {
      name          = "june-orchestrator"
      port          = 8080
      path          = "/v1/*"
      build_timeout = "1800s"
      machine_type  = "E2_HIGHCPU_8"
      disk_size     = 50
    }
  }
}

# Artifact Registry Module
module "artifact_registry" {
  source = "./modules/artifact-registry"
  
  project_id    = var.project_id
  region        = var.region
  repository_id = "june"
  description   = "June AI Platform Docker Images"
  labels        = local.common_labels
}

# Cloud Build Module  
module "cloud_build" {
  source = "./modules/cloud-build"
  
  project_id            = var.project_id
  region               = var.region
  environment          = var.environment
  services             = local.services
  github_owner         = var.github_owner
  github_repo          = var.github_repo
  branch              = var.build_branch
  artifact_registry_url = module.artifact_registry.repository_url
  labels              = local.common_labels
  
  depends_on = [module.artifact_registry]
}

# Harbor Registry Module
module "harbor_registry" {
  source = "./modules/harbor-registry"
  
  # GKE cluster information
  project_id       = var.project_id
  cluster_name     = var.cluster_name
  cluster_location = var.region
  
  # Harbor configuration
  harbor_namespace      = "harbor-system"
  harbor_admin_password = var.harbor_admin_password
  harbor_external_url   = "http://harbor.${var.domain_name}"
  harbor_hostname       = "harbor.${var.domain_name}"
  harbor_chart_version  = "1.15.0"
  
  # Storage configuration (optimized for single pod)
  storage_class         = "standard-rwo"  # GKE standard storage class
  registry_storage_size = var.harbor_registry_storage_size
  database_storage_size = var.harbor_database_storage_size
  redis_storage_size    = var.harbor_redis_storage_size
  
  # Feature configuration
  enable_trivy_scanning   = var.enable_trivy_scanning
  enable_metrics         = var.enable_harbor_metrics
  create_ingress         = var.create_harbor_ingress
  create_internal_service = true  # Always create internal service
  
  # TLS and ingress configuration
  enable_tls      = var.enable_harbor_tls
  tls_secret_name = "harbor-tls-cert"
  static_ip_name  = var.harbor_static_ip_name
  
  ingress_annotations = {
    "kubernetes.io/ingress.class" = "gce"
    "kubernetes.io/ingress.global-static-ip-name" = var.harbor_static_ip_name
  }
  
  # Node placement (optional)
  node_selector = var.harbor_node_selector
  tolerations   = var.harbor_tolerations
  
  # Labels
  labels = merge(local.common_labels, {
    "app.kubernetes.io/name"      = "harbor"
    "app.kubernetes.io/component" = "registry"
  })
  
  # Ensure cluster exists before deploying Harbor
  depends_on = [data.google_container_cluster.june_cluster]
}