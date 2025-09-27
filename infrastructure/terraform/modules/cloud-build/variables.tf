variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "services" {
  description = "Service configurations"
  type = map(object({
    name          = string
    port          = number
    path          = string
    build_timeout = string
    machine_type  = string
    disk_size     = number
  }))
}

variable "github_owner" {
  description = "GitHub owner"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository"
  type        = string
}

variable "branch" {
  description = "Branch pattern"
  type        = string
}

variable "artifact_registry_url" {
  description = "Artifact Registry URL"
  type        = string
}

variable "labels" {
  description = "Common labels"
  type        = map(string)
  default     = {}
}
