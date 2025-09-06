resource "google_artifact_registry_repository" "repo" {
  project       = var.project_id
  location      = var.region
  repository_id = var.name
  description   = "Container registry for ${var.name}"
  format        = "DOCKER"
}
output "registry_url" { value = "${var.region}-docker.pkg.dev/${var.project_id}/${var.name}" }
