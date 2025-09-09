# infra/envs/quarterly/main.tf
# REPLACE YOUR EXISTING main.tf WITH THIS VERSION

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

module "service_accounts" {
  source = "../../modules/service_accounts"
  # pass inputs as needed, e.g.:
  # project_id       = var.project_id
  # service_accounts = var.service_accounts
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

# Keycloak IDP
module "idp" {
  source       = "../../modules/cloud_run_service"
  service_name = "june-idp"
  region       = var.region
  image        = var.image_idp

  service_account  = local.runtime_sas["june-idp"]
  session_affinity = true

  cpu           = "2"
  memory        = "2Gi"
  port          = 8080
  min_instances = 1
  max_instances = 3

  args = [
    "start",
    "--http-enabled=true",
    "--proxy-headers=xforwarded",
    "--hostname=${var.KC_BASE_URL}"
  ]

  env = {
    KC_DB                       = "postgres"
    KC_DB_URL                   = var.KC_DB_URL
    KC_DB_USERNAME              = var.KC_DB_USERNAME
    KC_BOOTSTRAP_ADMIN_USERNAME = "admin"
    KC_BOOTSTRAP_ADMIN_PASSWORD = "bootstrap-temp"
    KC_HOSTNAME_STRICT          = "false"
    KC_CACHE                    = "local"
  }

  env_secrets = {
    KC_DB_PASSWORD = { secret = "KC_DB_PASSWORD", version = "latest" }
  }
}

# Orchestrator
module "orchestrator" {
  source       = "../../modules/cloud_run_service"
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
  source       = "../../modules/cloud_run_service"
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
  source       = "../../modules/cloud_run_service"
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

# Outputs
output "idp_url" {
  value = module.idp.url
}

output "orchestrator_url" {
  value = module.orchestrator.url
}

output "stt_url" {
  value = module.stt.url
}

output "tts_url" {
  value = module.tts.url
}