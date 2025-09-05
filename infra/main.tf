############################################
# Project services (APIs)
############################################
resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "serviceusage.googleapis.com",
    # Service APIs used by app code
    "speech.googleapis.com",
    "texttospeech.googleapis.com"
  ])
  project = var.project_id
  service = each.key
}

############################################
# Artifact Registry
############################################
##resource "google_artifact_registry_repository" "repo" {
##  project       = var.project_id
##  location      = var.region
##  repository_id = var.repo_name
##  format        = "DOCKER"
##  depends_on    = [google_project_service.apis]
##}

############################################
# STT service
############################################
module "stt" {
  source       = "./modules/cloud_run_service"
  project_id   = var.project_id
  region       = var.region
  service_name = "june-stt"
  image        = var.stt_image

  allow_unauthenticated = false

  env = {
    FIREBASE_PROJECT_ID = var.firebase_project_id
  }
}

# Allow orchestrator to invoke private STT via Cloud Run IAM
resource "google_cloud_run_service_iam_member" "stt_invoker_from_orchestrator" {
  project  = var.project_id
  location = var.region
  service  = "june-stt"
  role     = "roles/run.invoker"
  member   = "serviceAccount:${module.orchestrator.service_account_email}"
  depends_on = [module.stt, module.orchestrator]
}

############################################
# TTS service
############################################
module "tts" {
  source       = "./modules/cloud_run_service"
  project_id   = var.project_id
  region       = var.region
  service_name = "june-tts"
  image        = var.tts_image

  allow_unauthenticated = true

  env = {
    FIREBASE_PROJECT_ID = var.firebase_project_id
  }
}

############################################
# Compose URLs (derived automatically)
############################################
locals {
  stt_ws_url = replace("${module.stt.uri}/ws", "https://", "wss://")
  tts_url    = "${module.tts.uri}/v1/tts"
}

############################################
# Orchestrator service
############################################
module "orchestrator" {
  source       = "./modules/cloud_run_service"
  project_id   = var.project_id
  region       = var.region
  service_name = "june-orchestrator"
  image        = var.orchestrator_image

  allow_unauthenticated = true

  env = {
    FIREBASE_PROJECT_ID  = var.firebase_project_id
    STT_WS_URL           = local.stt_ws_url
    TTS_URL              = local.tts_url
    DEFAULT_LOCALE       = "en-US"
    DEFAULT_STT_RATE     = "16000"
    DEFAULT_STT_ENCODING = "pcm16"
    DEFAULT_TTS_ENCODING = "MP3"
    ORCH_STREAM_TTS      = tostring(var.orch_stream_tts)
    STT_REQUIRE_CLOUDRUN_AUTH = "true"
  }
}
