# Artifact Registry outputs
output "artifact_registry_repository_name" {
  description = "Name of the Artifact Registry repository"
  value       = google_artifact_registry_repository.june.name
}

output "artifact_registry_repository_url" {
  description = "URL of the Artifact Registry repository"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.june.repository_id}"
}

# Project outputs
output "project_id" {
  description = "GCP Project ID"
  value       = var.project_id
}

output "project_number" {
  description = "GCP Project Number"
  value       = data.google_project.current.number
}

output "region" {
  description = "GCP Region"
  value       = var.region
}

# Cloud Build outputs
output "june_tts_trigger_name" {
  description = "Name of the June TTS Cloud Build trigger"
  value       = google_cloudbuild_trigger.june_tts_build.name
}

output "june_orchestrator_trigger_name" {
  description = "Name of the June Orchestrator Cloud Build trigger"
  value       = google_cloudbuild_trigger.june_orchestrator_build.name
}

# GKE Cluster outputs
output "cluster_name" {
  description = "Name of the GKE cluster"
  value       = google_container_cluster.june_cluster.name
}

output "cluster_endpoint" {
  description = "Endpoint for GKE cluster"
  value       = google_container_cluster.june_cluster.endpoint
  sensitive   = true
}

output "cluster_location" {
  description = "Location of the GKE cluster"
  value       = google_container_cluster.june_cluster.location
}

output "kubectl_config_command" {
  description = "Command to configure kubectl"
  value       = "gcloud container clusters get-credentials ${google_container_cluster.june_cluster.name} --region ${google_container_cluster.june_cluster.location} --project ${var.project_id}"
}
