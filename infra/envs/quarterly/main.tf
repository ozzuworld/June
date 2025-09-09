terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38"
    }
  }
  backend "remote" {}
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# Use the service accounts module
module "service_accounts" {
  source            = "git::https://github.com/ozzuworld/June.git//infra/modules/service_accounts?ref=master"
  project_id        = var.project_id
  deployer_sa_email = var.deployer_sa_email
}

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

  runtime_sas = module.service_accounts.runtime_service_accounts
}

# Orchestrator
module "orchestrator" {
  source       = "git::https://github.com/ozzuworld/June.git//infra/modules/cloud_run_service?ref=master"
  service_name = "june-orchestrator"
  region       = var.region
  image        = var.image_orchestrator

  service_account = local.runtime_sas["june-orchestrator"]
  env             = local.base_env

  cpu           = "1"
  memory        = "512Mi"
  min_instances = 0
  max_instances = 20
}

# Speech-to-Text
module "stt" {
  source       = "git::https://github.com/ozzuworld/June.git//infra/modules/cloud_run_service?ref=master"
  service_name = "june-stt"
  region       = var.region
  image        = var.image_stt

  service_account = local.runtime_sas["june-stt"]
  env = {
    GEMINI_API_KEY = var.GEMINI_API_KEY
  }

  cpu           = "2"
  memory        = "1Gi"
  min_instances = 1
  max_instances = 10
}

# Text-to-Speech
module "tts" {
  source       = "git::https://github.com/ozzuworld/June.git//infra/modules/cloud_run_service?ref=master"
  service_name = "june-tts"
  region       = var.region
  image        = var.image_tts

  service_account = local.runtime_sas["june-tts"]
  env = {
    GEMINI_API_KEY = var.GEMINI_API_KEY
  }

  cpu           = "2"
  memory        = "1Gi"
  min_instances = 0
  max_instances = 10
}

# Outputs (remove idp_url since it's in june-idp.tf)
output "orchestrator_url" {
  value = module.orchestrator.url
}

output "stt_url" {
  value = module.stt.url
}

output "tts_url" {
  value = module.tts.url
}

