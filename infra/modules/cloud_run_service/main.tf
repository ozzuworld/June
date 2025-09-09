# Replace in main.tf - use standard Google module instead

module "orchestrator" {
  source  = "GoogleCloudPlatform/cloud-run/google"
  version = "~> 0.20"

  service_name = "june-orchestrator"
  project_id   = var.project_id
  location     = var.region
  image        = var.image_orchestrator

  service_account_email = local.runtime_sas["june-orchestrator"]
  
  env_vars = [
    { name = "NEON_DB_URL", value = var.NEON_DB_URL },
    { name = "UPSTASH_REDIS_REST_URL", value = var.UPSTASH_REDIS_REST_URL },
    { name = "UPSTASH_REDIS_REST_TOKEN", value = var.UPSTASH_REDIS_REST_TOKEN },
    { name = "QDRANT_URL", value = var.QDRANT_URL },
    { name = "QDRANT_API_KEY", value = var.QDRANT_API_KEY },
    { name = "GEMINI_API_KEY", value = var.GEMINI_API_KEY },
    { name = "KC_BASE_URL", value = var.KC_BASE_URL },
    { name = "KC_REALM", value = var.KC_REALM },
    { name = "KC_CLIENT_ID", value = var.KC_CLIENT_ID },
    { name = "KC_CLIENT_SECRET", value = var.KC_CLIENT_SECRET }
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