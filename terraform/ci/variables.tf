# terraform/ci/variables.tf

variable "project_id" {
  type = string
}

variable "project_number" {
  type = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "github_org" {
  type = string
}

variable "github_repo" {
  type = string
}

variable "wif_pool_id" {
  type    = string
  default = "github-pool"
}

variable "wif_provider_id" {
  type    = string
  default = "github-provider"
}

# List of app secrets to create (names only; add versions out-of-band)
variable "secrets" {
  type = list(string)
  default = [
    "NEON_DB_URL", "NEON_API_KEY",
    "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN", "UPSTASH_REDIS_URL",
    "QDRANT_API_KEY", "QDRANT_URL",
    "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_ENDPOINT", "R2_BUCKET",
    "CLOUDFLARE_API_TOKEN"
  ]
}
