variable "project_id" { type = string }
variable "region"     { type = string  default = "us-central1" }

variable "image_orchestrator" { type = string }
variable "image_stt"          { type = string }
variable "image_tts"          { type = string }

# Shared envs from Doppler
variable "NEON_DB_URL"              { type = string }
variable "UPSTASH_REDIS_REST_URL"   { type = string }
variable "UPSTASH_REDIS_REST_TOKEN" { type = string }
variable "QDRANT_URL"               { type = string  default = "" }
variable "QDRANT_API_KEY"           { type = string  default = "" }
variable "GEMINI_API_KEY"           { type = string }
variable "KC_BASE_URL"              { type = string }
variable "KC_REALM"                 { type = string  default = "june" }
variable "KC_CLIENT_ID"             { type = string  default = "" }
variable "KC_CLIENT_SECRET"         { type = string  default = "" }
