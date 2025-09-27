# Infrastructure Outputs
output "project_info" {
  description = "Project information"
  value = {
    project_id  = var.project_id
    region      = var.region
    environment = var.environment
  }
}

output "artifact_registry" {
  description = "Artifact Registry information"
  value = {
    repository_url = module.artifact_registry.repository_url
    repository_id  = module.artifact_registry.repository_id
  }
}

output "cloud_build" {
  description = "Cloud Build configuration"
  value = {
    docker_images   = module.cloud_build.docker_images
    build_commands  = module.cloud_build.build_commands
    service_account = module.cloud_build.service_account_email
  }
  sensitive = true
}

# Vast.ai Ready URLs
output "vastai_images" {
  description = "Docker images ready for Vast.ai deployment"
  value = {
    june_tts          = "${module.artifact_registry.repository_url}/june-tts:latest"
    june_orchestrator = "${module.artifact_registry.repository_url}/june-orchestrator:latest"
  }
}
