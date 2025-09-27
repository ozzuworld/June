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
