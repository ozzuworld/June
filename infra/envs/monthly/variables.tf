variable "project_id"       { type = string }
variable "region"           { type = string  default = "us-central1" }

variable "orchestrator_image" { type = string }
variable "stt_image"          { type = string }
variable "tts_image"          { type = string }

# External persistent services
variable "kc_base_url"      { type = string }  # e.g., https://auth.example.com
variable "kc_realm"         { type = string  default = "june" }
variable "kc_client_id"     { type = string }
variable "kc_client_secret" { type = string }
variable "neon_db_url"      { type = string }  # postgres://user:pass@host/db
variable "gemini_api_key"   { type = string }
