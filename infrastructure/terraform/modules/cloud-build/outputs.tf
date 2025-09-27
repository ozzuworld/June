output "service_account_email" {
  description = "Cloud Build service account email"
  value       = "${data.google_project.current.number}@cloudbuild.gserviceaccount.com"
}

output "docker_images" {
  description = "Docker image URLs for each service"
  value = {
    for service_key, service in var.services :
    service_key => "${var.artifact_registry_url}/${service.name}:latest"
  }
}

output "build_commands" {
  description = "Manual build commands for each service"
  value = {
    for service_key, service in var.services :
    service_key => "gcloud builds submit June/services/${service_key} --config=build-configs/${service_key}-cloudbuild.yaml"
  }
}

output "build_config_files" {
  description = "Generated build configuration files"
  value = {
    for service_key, service in var.services :
    service_key => "${path.root}/build-configs/${service_key}-cloudbuild.yaml"
  }
}
