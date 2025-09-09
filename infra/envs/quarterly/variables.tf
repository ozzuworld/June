# infra/envs/quarterly/variables.tf
# REPLACE YOUR EXISTING FILE WITH THIS CLEAN VERSION

# Core infrastructure
variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP region"
  type        = string
  default     = "us-central1"
}

# Container images - grouped for clarity
variable "image_orchestrator" {
  description = "Container image for orchestrator service"
  type        = string
}

variable "image_stt" {
  description = "Container image for STT service"
  type        = string
}

variable "image_tts" {
  description = "Container image for TTS service"
  type        = string
}

variable "image_idp" {
  description = "Container image for Keycloak IDP"
  type        = string
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

# Keycloak configuration - consolidated and clean
variable "KC_BASE_URL" {
  description = "Keycloak base URL (Cloud Run URL or custom domain)"
  type        = string
}

variable "KC_DB_URL" {
  description = "Keycloak database JDBC URL"
  type        = string
  sensitive   = true
}

variable "KC_DB_USERNAME" {
  description = "Keycloak database username"
  type        = string
  sensitive   = true
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