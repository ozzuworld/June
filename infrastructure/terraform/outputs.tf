# Artifact Registry Outputs
output "artifact_registry_url" {
  description = "URL of the Artifact Registry repository"
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.june.repository_id}"
}

output "artifact_registry_id" {
  description = "ID of the Artifact Registry repository"
  value       = google_artifact_registry_repository.june.repository_id
}

# Cloud Build Outputs
output "cloud_build_service_account_email" {
  description = "Cloud Build service account email"
  value       = "${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

output "docker_hub_images" {
  description = "Docker Hub image URLs"
  value = {
    june_tts          = "ozzuworld/june-tts:latest"
    june_orchestrator = "ozzuworld/june-orchestrator:latest"
  }
}

output "artifact_registry_images" {
  description = "Artifact Registry image URLs"
  value = {
    june_tts          = "${var.region}-docker.pkg.dev/${var.project_id}/june/june-tts:latest"
    june_orchestrator = "${var.region}-docker.pkg.dev/${var.project_id}/june/june-orchestrator:latest"
  }
}

# Setup Instructions
output "setup_instructions" {
  description = "Next steps to complete the setup"
  value = {
    create_secrets = [
      "echo -n 'ozzuworld' | gcloud secrets create dockerhub-username --data-file=- --project=${var.project_id}",
      "echo -n 'YOUR_DOCKERHUB_TOKEN' | gcloud secrets create dockerhub-token --data-file=- --project=${var.project_id}"
    ]
    
    grant_permissions = [
      "gcloud projects add-iam-policy-binding ${var.project_id} --member='serviceAccount:${data.google_project.current.number}@cloudbuild.gserviceaccount.com' --role='roles/secretmanager.secretAccessor'"
    ]
    
    add_cloudbuild_files = [
      "Add cloudbuild.yaml to June/services/june-tts/",
      "Add cloudbuild.yaml to June/services/june-orchestrator/",
      "Push changes to master branch to trigger builds"
    ]
  }
}
