variable "project_id" {}
variable "region" { default = "us-central1" }

resource "google_artifact_registry_repository" "june" {
  project       = var.project_id
  location      = var.region
  repository_id = "june"
  description   = "Container images for June services"
  format        = "DOCKER"
}
