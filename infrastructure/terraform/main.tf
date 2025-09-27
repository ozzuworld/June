# June AI Platform - Cloud Build Infrastructure
# Author: Infrastructure Team
# Purpose: Automated Docker builds for microservices

terraform {
  required_version = ">= 1.5"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.0"
    }
  }

  # Backend configuration - use GCS for production
  backend "gcs" {
    bucket = "june-terraform-state"
    prefix = "cloud-build"
  }
}

# Provider configuration
provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = local.common_labels
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# Local values for computed configurations
locals {
  environment = var.environment

  # Common resource labeling
  common_labels = {
    project     = "june-ai-platform"
    environment = var.environment
    managed_by  = "terraform"
    team        = "platform"
    cost_center = "engineering"
  }

  # Service definitions with proper naming
  services = {
    june-tts = {
      name          = "june-tts"
      port          = 8000
      path          = "/tts/*"
      build_timeout = "4800s" # 80 minutes for ML models
      machine_type  = "E2_HIGHCPU_8"
      disk_size     = 100
    }
    june-orchestrator = {
      name          = "june-orchestrator"
      port          = 8080
      path          = "/v1/*"
      build_timeout = "1800s" # 30 minutes
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

  labels = local.common_labels

  tags = ["docker", "microservices", var.environment]
}

# Cloud Build Module  
module "cloud_build" {
  source = "./modules/cloud-build"

  project_id  = var.project_id
  region      = var.region
  environment = var.environment

  # Service configurations
  services = local.services

  # Repository configuration
  github_owner = var.github_owner
  github_repo  = var.github_repo
  branch       = var.build_branch

  # Artifact Registry dependency
  artifact_registry_url = module.artifact_registry.repository_url

  # Labels and tags
  labels = local.common_labels

  depends_on = [module.artifact_registry]
}
