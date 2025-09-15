# infra/envs/quarterly/variables.tf - FIXED SERVICE NAMES AND CREDENTIALS

# Project settings
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region to deploy services"
  type        = string
  default     = "us-central1"
}

# Container images
variable "image_idp" {
  description = "June IDP (Keycloak) container image"
  type        = string
}

variable "image_orchestrator" {
  description = "June Orchestrator container image"
  type        = string
}

variable "image_stt" {
  description = "June STT container image"
  type        = string
}

variable "image_tts" {
  description = "June TTS (Chatterbox) container image"
  type        = string
}

# Keycloak configuration
variable "KC_BASE_URL" {
  description = "Keycloak base URL"
  type        = string
}

variable "KC_DB_URL" {
  description = "Keycloak database connection URL"
  type        = string
}

variable "KC_DB_USERNAME" {
  description = "Keycloak database username"
  type        = string
}

variable "KC_REALM" {
  description = "Keycloak realm name"
  type        = string
  default     = "june"
}

variable "KC_CLIENT_ID" {
  description = "Keycloak client ID"
  type        = string
}

variable "KC_CLIENT_SECRET" {
  description = "Keycloak client secret"
  type        = string
}

# FIXED: Service client credentials
variable "ORCHESTRATOR_CLIENT_ID" {
  description = "Orchestrator service client ID"
  type        = string
}

variable "ORCHESTRATOR_CLIENT_SECRET" {
  description = "Orchestrator service client secret"
  type        = string
}

variable "STT_CLIENT_ID" {
  description = "STT service client ID"
  type        = string
}

variable "STT_CLIENT_SECRET" {
  description = "STT service client secret"
  type        = string
}

variable "TTS_CLIENT_ID" {
  description = "TTS (Chatterbox) service client ID"
  type        = string
}

variable "TTS_CLIENT_SECRET" {
  description = "TTS (Chatterbox) service client secret"
  type        = string
}

# External services
variable "NEON_DB_URL" {
  description = "Neon database connection URL"
  type        = string
}

variable "UPSTASH_REDIS_REST_URL" {
  description = "Upstash Redis REST URL"
  type        = string
}

variable "UPSTASH_REDIS_REST_TOKEN" {
  description = "Upstash Redis REST token"
  type        = string
}

variable "QDRANT_URL" {
  description = "Qdrant vector database URL"
  type        = string
}

variable "QDRANT_API_KEY" {
  description = "Qdrant API key"
  type        = string
}

variable "GEMINI_API_KEY" {
  description = "Google Gemini API key"
  type        = string
}

# CI/CD (optional, for manual deployment)
variable "deployer_sa_email" {
  description = "Service account email for the GitHub Actions deployer"
  type        = string
  default     = ""
}