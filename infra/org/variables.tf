variable "org_id"          { type = string }
variable "billing_account" { type = string }
variable "seed_project_id" { type = string } # provider bootstrap project for API calls
variable "default_region"  { type = string  default = "us-central1" }
variable "month_suffix"    { type = string } # e.g., 2025-09 or github.run_id
