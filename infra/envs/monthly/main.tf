terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38"
    }
  }
  backend "remote" {} # Fill workspace
}

provider "google" {
  project = var.project_id
  region  = var.region
}

module "orchestrator" {
  source       = "../../modules/cloud_run_service"
  service_name = "june-orchestrator"
  region       = var.region
  image        = var.orchestrator_image
  env = {
    KC_BASE_URL        = var.kc_base_url
    KC_REALM           = var.kc_realm
    KC_CLIENT_ID       = var.kc_client_id
    KC_CLIENT_SECRET   = var.kc_client_secret
    NEON_DB_URL        = var.neon_db_url
    GEMINI_API_KEY     = var.gemini_api_key
  }
  min_instances = 0
  max_instances = 20
  cpu           = "1"
  memory        = "1Gi"
}

module "stt" {
  source       = "../../modules/cloud_run_service"
  service_name = "june-stt"
  region       = var.region
  image        = var.stt_image
  env = {
    GEMINI_API_KEY     = var.gemini_api_key
  }
  min_instances = 0
  max_instances = 10
  cpu           = "1"
  memory        = "1Gi"
}

module "tts" {
  source       = "../../modules/cloud_run_service"
  service_name = "june-tts"
  region       = var.region
  image        = var.tts_image
  env = {
    GEMINI_API_KEY     = var.gemini_api_key
  }
  min_instances = 0
  max_instances = 10
  cpu           = "1"
  memory        = "1Gi"
}

output "orchestrator_url" { value = module.orchestrator.url }
output "stt_url"          { value = module.stt.url }
output "tts_url"          { value = module.tts.url }
