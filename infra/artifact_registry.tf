resource "google_artifact_registry_repository" "apps" {
  location      = var.region
  repository_id = var.repo_name
  description   = "Container images for June microservices"
  format        = "DOCKER"
}
