# --- june-auth specific variables ---
variable "june_auth_image" {
  type = string
  description = "Container image for the june-auth service"
}

variable "june_auth_service_name" {
  type    = string
  default = "june-auth"
}

variable "june_auth_allow_unauthenticated" {
  type    = bool
  default = true
  description = "Whether june-auth Cloud Run should allow unauthenticated calls. App still enforces Firebase auth."
}

# App config
variable "june_auth_totp_issuer"         { type = string, default = "June Voice" }
variable "june_auth_totp_alg"            { type = string, default = "SHA1" }
variable "june_auth_totp_digits"         { type = number, default = 6 }
variable "june_auth_totp_period"         { type = number, default = 30 }
variable "june_auth_mfa_jwt_ttl_seconds" { type = number, default = 600 }

# Optional: Create secret versions via Terraform (leaks to TF state if used)
variable "june_auth_create_secret_versions" { type = bool, default = false }
variable "june_auth_fernet_key"            { type = string, sensitive = true, default = null }
variable "june_auth_mfa_jwt_secret"        { type = string, sensitive = true, default = null }
