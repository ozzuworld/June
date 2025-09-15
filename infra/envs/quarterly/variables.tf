# infra/envs/quarterly/variables.tf - FIXED VARIABLE NAMES

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

variable "deployer_sa_email" {
  description = "The service account email used in GitHub Actions with WIF"
  type        = string
  default     = ""
}

# Container images
variable "image_idp" { 
  type = string 
}

variable "image_orchestrator" {
  description = "Container image for orchestrator service"
  type        = string
}

variable "image_stt" {
  description = "Container image for STT service"
  type        = string
}

# FIXED: Use image_tts instead of image_chatterbox_tts
variable "image_tts" {
  description = "Container image for TTS service (Coqui TTS engine)"
  type        = string
}

# Keycloak specific variables
variable "KC_BASE_URL" { 
  type = string 
  description = "https://june-idp-<hash>-us-central1.a.run.app or custom domain"
}

variable "KC_DB_URL" { 
  type = string 
  description = "jdbc:postgresql://HOST:5432/DB?sslmode=require"
}

variable "KC_DB_USERNAME" { 
  type = string 
}

variable "KC_REALM" {
  description = "Keycloak realm name"
  type        = string
  default     = "june"
}

variable "KC_CLIENT_ID" {
  description = "Keycloak client ID"
  type        = string
  default     = ""
}

variable "KC_CLIENT_SECRET" {
  description = "Keycloak client secret"
  type        = string
  default     = ""
  sensitive   = true
}

# Service client credentials
variable "STT_CLIENT_ID" {
  description = "Keycloak client ID for STT service"
  type        = string
  default     = ""
}

variable "STT_CLIENT_SECRET" {
  description = "Keycloak client secret for STT service"
  type        = string
  default     = ""
  sensitive   = true
}

# FIXED: Use TTS_CLIENT_* instead of CHATTERBOX_CLIENT_*
variable "TTS_CLIENT_ID" {
  description = "Keycloak client ID for TTS service"
  type        = string
  default     = ""
}

variable "TTS_CLIENT_SECRET" {
  description = "Keycloak client secret for TTS service"
  type        = string
  default     = ""
  sensitive   = true
}

# External service URLs and credentials
variable "NEON_DB_URL" {
  description = "Neon PostgreSQL connection string"
  type        = string
  sensitive   = true
}

variable "UPSTASH_REDIS_REST_URL" {
  description = "Upstash Redis REST endpoint"
  type        = string
  sensitive   = true
}

variable "UPSTASH_REDIS_REST_TOKEN" {
  description = "Upstash Redis REST token"
  type        = string
  sensitive   = true
}

variable "QDRANT_URL" {
  description = "Qdrant vector database URL"
  type        = string
  default     = ""
}

variable "QDRANT_API_KEY" {
  description = "Qdrant API key"
  type        = string
  default     = ""
  sensitive   = true
}

variable "GEMINI_API_KEY" {
  description = "Google Gemini API key"
  type        = string
  sensitive   = true
}