# File: infra/envs/quarterly/chatterbox-tts.tf

# Chatterbox TTS service configuration
resource "google_service_account" "chatterbox_tts_sa" {
  account_id   = "chatterbox-tts-svc"
  display_name = "Chatterbox TTS Cloud Run SA"
}

# Grant deployer SA access to impersonate Chatterbox TTS SA
resource "google_service_account_iam_member" "deployer_can_impersonate_chatterbox_tts" {
  service_account_id = google_service_account.chatterbox_tts_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.runtime_sas["june-orchestrator"]}"
}

# Chatterbox TTS Cloud Run service
module "chatterbox_tts" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-chatterbox-tts"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_chatterbox_tts

  service_account_email = google_service_account.chatterbox_tts_sa.email
  
  env_vars = [
    { name = "KC_BASE_URL", value = var.KC_BASE_URL },
    { name = "KC_REALM", value = var.KC_REALM },
    { name = "CHATTERBOX_CLIENT_ID", value = var.CHATTERBOX_CLIENT_ID },
    { name = "CHATTERBOX_CLIENT_SECRET", value = var.CHATTERBOX_CLIENT_SECRET },
    { name = "DEVICE", value = "cpu" },  # Use GPU if available
    { name = "LOG_LEVEL", value = "INFO" },
    { name = "ENABLE_MULTILINGUAL", value = "true" },
    { name = "ENABLE_VOICE_CLONING", value = "true" },
    { name = "ENABLE_EMOTION_CONTROL", value = "true" },
    { name = "MAX_TEXT_LENGTH", value = "5000" }
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

  ports = {
    name = "http1"
    port = 8080
  }
}

output "chatterbox_tts_url" {
  value = module.chatterbox_tts.service_url
  description = "URL of the Chatterbox TTS service"
  } 