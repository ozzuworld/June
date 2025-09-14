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

# Orchestrator using the official module - UPDATED for Kokoro TTS
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
      # UPDATED: Point to Kokoro TTS instead of legacy TTS
      TTS_SERVICE_URL = "https://june-kokoro-tts-359243954.us-central1.run.app"
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

# Legacy Text-to-Speech (keeping for backward compatibility)
module "tts" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-tts"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_tts

  service_account_email = local.runtime_sas["june-tts"]
  
  env_vars = [
    { name = "KC_BASE_URL", value = var.KC_BASE_URL },
    { name = "KC_REALM", value = var.KC_REALM },
    { name = "TTS_CLIENT_ID", value = var.TTS_CLIENT_ID },
    { name = "TTS_CLIENT_SECRET", value = var.TTS_CLIENT_SECRET },
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

# NEW: Kokoro TTS service
module "kokoro_tts" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-kokoro-tts"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_kokoro_tts

  service_account_email = local.runtime_sas["june-kokoro-tts"]
  
  env_vars = [
    { name = "KC_BASE_URL", value = var.KC_BASE_URL },
    { name = "KC_REALM", value = var.KC_REALM },
    { name = "KOKORO_CLIENT_ID", value = var.KOKORO_CLIENT_ID },
    { name = "KOKORO_CLIENT_SECRET", value = var.KOKORO_CLIENT_SECRET },
    { name = "MODEL_PATH", value = "/app/models" },
    { name = "DEVICE", value = "cpu" },
    { name = "LOG_LEVEL", value = "INFO" }
  ]

  limits = {
    cpu    = "2000m"  # 2 CPU cores for model inference
    memory = "4Gi"    # 4GB RAM for model loading
  }

  template_annotations = {
    "autoscaling.knative.dev/minScale" = "0"  # Scale to zero
    "autoscaling.knative.dev/maxScale" = "5"  # Limit instances
    "run.googleapis.com/startup-cpu-boost" = "true"  # Faster cold starts
  }

  timeout_seconds = 900  # 15 minutes for model loading
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

# NEW: Kokoro TTS output
output "kokoro_tts_url" {
  value = module.kokoro_tts.service_url
  description = "URL of the Kokoro TTS service"
}

# NOTE: IDP module and its output are in june-idp.tf