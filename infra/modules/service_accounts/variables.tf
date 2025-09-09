# infra/modules/service_accounts/variables.tf

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "deployer_sa_email" {
  description = "Service account email for the GitHub Actions deployer (e.g., github-deployer@project.iam.gserviceaccount.com)"
  type        = string
  default     = ""
}