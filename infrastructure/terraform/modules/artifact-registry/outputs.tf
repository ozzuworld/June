output "repository_id" {
  description = "The ID of the created repository"
  value       = google_artifact_registry_repository.main.repository_id
}

output "repository_url" {
  description = "The full repository URL"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.main.repository_id}"
}

output "repository_name" {
  description = "The name of the repository"
  value       = google_artifact_registry_repository.main.name
}
