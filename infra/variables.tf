variable "project_id" {
  description = "Google Cloud project ID (e.g., main-buffer-469817-v7)"
  type        = string
}

variable "region" {
  description = "Default region for regional resources"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "Zone for zonal resources (e.g., us-central1-a)"
  type        = string
}

variable "repo_name" {
  description = "Artifact Registry repository for container images"
  type        = string
  default     = "apps"
}

variable "orchestrator_image" {
  description = "Container image for the orchestrator service"
  type        = string
}

variable "stt_image" {
  description = "Container image for the speech-to-text (STT) service"
  type        = string
}

variable "tts_image" {
  description = "Container image for the text-to-speech (TTS) service"
  type        = string
}

variable "firebase_project_id" {
  description = "Firebase project ID (typically same as project_id)"
  type        = string
}

variable "orch_stream_tts" {
  description = "Enable streaming TTS in the orchestrator"
  type        = bool
  default     = false
}

variable "domain" {
  description = "Base domain (e.g., allsafe.world). Keycloak will be at auth.<domain> and orchestrator at orch.<domain>"
  type        = string
}

# DB credentials for Keycloak database
variable "kc_db_user" {
  type    = string
  default = "keycloak"
}

variable "kc_db_password" {
  type      = string
  default   = ""
  sensitive = true
}

variable "kc_db_name" {
  type    = string
  default = "keycloak"
}

# Optional bootstrap admin password for Keycloak (if blank, auto-generate)
variable "kc_admin_password" {
  type      = string
  default   = ""
  sensitive = true
}

# Tag used to build image URIs when modules expect a tag
variable "image_tag" {
  description = "Docker image tag to deploy (e.g., a commit SHA like abc123)."
  type        = string
  default     = "initial" # change in CLI or tfvars as needed
}
