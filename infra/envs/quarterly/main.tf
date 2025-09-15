# infra/envs/quarterly/main.tf - CHATTERBOX TTS ONLY
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
    for k, v in merge(local.base_env, {
      # Point to Chatterbox TTS (the ONLY TTS service)
      TTS_SERVICE_URL = "https://june-chatterbox-tts-359243954.us-central1.run.app"
      STT_SERVICE_URL = "https://june-stt-359243954.us-central1.run.app"
    }) : {
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
    { name = "KC_BASE_URL", value = var.KC_BASE_URL },
    { name = "KC_REALM", value = var.KC_REALM },
    { name = "STT_CLIENT_ID", value = var.STT_CLIENT_ID },
    { name = "STT_CLIENT_SECRET", value = var.STT_CLIENT_SECRET },
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

# Chatterbox TTS - THE ONLY TTS SERVICE
module "chatterbox_tts" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-chatterbox-tts"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_chatterbox_tts

  service_account_email = local.runtime_sas["june-chatterbox-tts"]
  
  env_vars = [
    { name = "KC_BASE_URL", value = var.KC_BASE_URL },
    { name = "KC_REALM", value = var.KC_REALM },
    { name = "CHATTERBOX_CLIENT_ID", value = var.CHATTERBOX_CLIENT_ID },
    { name = "CHATTERBOX_CLIENT_SECRET", value = var.CHATTERBOX_CLIENT_SECRET },
    { name = "DEVICE", value = "cpu" },
    { name = "LOG_LEVEL", value = "INFO" },
    { name = "ENABLE_MULTILINGUAL", value = "true" },
    { name = "ENABLE_VOICE_CLONING", value = "true" },
    { name = "ENABLE_EMOTION_CONTROL", value = "true" },
    { name = "MAX_TEXT_LENGTH", value = "5000" },
    { name = "MODELS_PATH", value = "/app/models" },
    { name = "VOICES_PATH", value = "/app/voices" },
    { name = "CACHE_PATH", value = "/app/cache" }
  ]

  limits = {
    cpu    = "4000m"  # 4 CPU cores for better model performance
    memory = "8Gi"    # 8GB RAM for model loading and processing
  }

  template_annotations = {
    "autoscaling.knative.dev/minScale" = "0"   # Scale to zero when not in use
    "autoscaling.knative.dev/maxScale" = "10"  # Limit concurrent instances
    "run.googleapis.com/startup-cpu-boost" = "true"  # Faster cold starts
    "run.googleapis.com/execution-environment" = "gen2"  # Better performance
  }

  # Extended timeout for model loading and synthesis
  timeout_seconds = 1800  # 30 minutes
}

# Outputs
output "orchestrator_url" {
  value = module.orchestrator.service_url
}

output "stt_url" {
  value = module.stt.service_url
}

output "chatterbox_tts_url" {
  value = module.chatterbox_tts.service_url
  description = "URL of the Chatterbox TTS service"
}

# NOTE: IDP module and its output are in june-idp.tf