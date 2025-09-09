# infra/envs/quarterly/main.tf
terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 6.0.0, < 7.0.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 6.0.0, < 7.0.0"
    }
  }
  backend "remote" {
    organization = "allsafe-world"
    
    workspaces {
      name = "quarterly"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

provider "google-beta" {
  project = var.project_id
  region  = var.region
}

# Service accounts are defined in service_accounts.tf

# Common environment variables
locals {
  base_env = {
    NEON_DB_URL              = var.NEON_DB_URL
    UPSTASH_REDIS_REST_URL   = var.UPSTASH_REDIS_REST_URL
    UPSTASH_REDIS_REST_TOKEN = var.UPSTASH_REDIS_REST_TOKEN
    QDRANT_URL               = var.QDRANT_URL
    QDRANT_API_KEY           = var.QDRANT_API_KEY
    GEMINI_API_KEY           = var.GEMINI_API_KEY
    KC_BASE_URL              = var.KC_BASE_URL
    KC_REALM                 = var.KC_REALM
    KC_CLIENT_ID             = var.KC_CLIENT_ID
    KC_CLIENT_SECRET         = var.KC_CLIENT_SECRET
  }

  # Reference the local service accounts from service_accounts.tf
  runtime_sas = local.runtime_service_accounts
}

# Orchestrator using the official module
module "orchestrator" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-orchestrator"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_orchestrator

  service_account_email = local.runtime_sas["june-orchestrator"]
  
  env_vars = [
    for k, v in local.base_env : {
      name  = k
      value = v
    }
  ]

  limits = {
    cpu    = "1000m"
    memory = "512Mi"
  }

  template_annotations = {
    "autoscaling.knative.dev/minScale" = "0"
    "autoscaling.knative.dev/maxScale" = "20"
  }
}

# Speech-to-Text using the official module
module "stt" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-stt"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_stt

  service_account_email = local.runtime_sas["june-stt"]
  
  env_vars = [
    { name = "GEMINI_API_KEY", value = var.GEMINI_API_KEY }
  ]

  limits = {
    cpu    = "2000m"
    memory = "1Gi"
  }

  template_annotations = {
    "autoscaling.knative.dev/minScale" = "1"
    "autoscaling.knative.dev/maxScale" = "10"
  }
}

# Text-to-Speech using the official module
module "tts" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-tts"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_tts

  service_account_email = local.runtime_sas["june-tts"]
  
  env_vars = [
    { name = "GEMINI_API_KEY", value = var.GEMINI_API_KEY }
  ]

  limits = {
    cpu    = "2000m"
    memory = "1Gi"
  }

  template_annotations = {
    "autoscaling.knative.dev/minScale" = "0"
    "autoscaling.knative.dev/maxScale" = "10"
  }
}

# Outputs
output "orchestrator_url" {
  value = module.orchestrator.service_url
}

output "stt_url" {
  value = module.stt.service_url
}

output "tts_url" {
  value = module.tts.service_url
}

# NOTE: IDP module and its output are in june-idp.tf