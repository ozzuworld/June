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
}

module "orchestrator" {
  source       = "../../modules/cloud_run_service"
  service_name = "june-orchestrator"
  region       = var.region
  image        = var.image_orchestrator
  env          = local.base_env
  min_instances = 0
  max_instances = 20
}

module "stt" {
  source       = "../../modules/cloud_run_service"
  service_name = "june-stt"
  region       = var.region
  image        = var.image_stt
  env = {
    GEMINI_API_KEY = var.GEMINI_API_KEY
  }
  min_instances = 0
  max_instances = 10
}

module "tts" {
  source       = "../../modules/cloud_run_service"
  service_name = "june-tts"
  region       = var.region
  image        = var.image_tts
  env = {
    GEMINI_API_KEY = var.GEMINI_API_KEY
  }
  min_instances = 0
  max_instances = 10
}

output "orchestrator_url" { value = module.orchestrator.url }
output "stt_url"          { value = module.stt.url }
output "tts_url"          { value = module.tts.url }
