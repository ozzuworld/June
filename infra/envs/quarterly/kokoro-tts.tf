# infra/envs/quarterly/kokoro-tts.tf
# Kokoro TTS service configuration

# Service Account for Kokoro TTS
resource "google_service_account" "kokoro_tts_sa" {
  account_id   = "kokoro-tts-svc"
  display_name = "Kokoro TTS Cloud Run SA"
}

# Grant deployer SA access to impersonate Kokoro TTS SA
resource "google_service_account_iam_member" "deployer_can_impersonate_kokoro_tts" {
  service_account_id = google_service_account.kokoro_tts_sa.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${local.runtime_sas["june-orchestrator"]}" # Use orchestrator SA for deployment
}

# Kokoro TTS Cloud Run service
module "kokoro_tts" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.21"

  service_name = "june-kokoro-tts"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_kokoro_tts

  service_account_email = google_service_account.kokoro_tts_sa.email
  
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
    cpu    = "2000m"  # 2 CPU cores for better model performance
    memory = "4Gi"    # 4GB RAM for model loading
  }

  template_annotations = {
    "autoscaling.knative.dev/minScale" = "0"  # Scale to zero when not in use
    "autoscaling.knative.dev/maxScale" = "5"  # Limit concurrent instances
    "run.googleapis.com/startup-cpu-boost" = "true"  # Faster cold starts
  }

  # Extended timeout for model loading
  timeout_seconds = 900  # 15 minutes

  ports = {
    name = "http1"
    port = 8080
  }
}

output "kokoro_tts_url" {
  value = module.kokoro_tts.service_url
  description = "URL of the Kokoro TTS service"
}