
resource "google_artifact_registry_repository" "june" {
  project       = var.project_id
  location      = var.region
  repository_id = "june"
  format        = "DOCKER"
  description   = "Container images for June services"
}
