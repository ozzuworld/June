# Artifact Registry Outputs
output "artifact_registry_url" {
  description = "URL of the Artifact Registry repository"
  value       = module.artifact_registry.repository_url
}

output "artifact_registry_id" {
  description = "ID of the Artifact Registry repository"
  value       = module.artifact_registry.repository_id
}

# Cloud Build Outputs
output "cloud_build_service_account_email" {
  description = "Cloud Build service account email"
  value       = module.cloud_build.service_account_email
}

output "cloud_build_docker_images" {
  description = "Docker image URLs for each service"
  value       = module.cloud_build.docker_images
}

output "cloud_build_commands" {
  description = "Manual build commands for each service"
  value       = module.cloud_build.build_commands
}

# Harbor Registry Outputs
output "harbor_namespace" {
  description = "Kubernetes namespace where Harbor is deployed"
  value       = module.harbor_registry.harbor_namespace
}

output "harbor_external_url" {
  description = "External URL for Harbor registry"
  value       = module.harbor_registry.harbor_external_url
}

output "harbor_registry_endpoint" {
  description = "Harbor registry endpoint for Docker commands"
  value       = module.harbor_registry.harbor_registry_endpoint
}

output "harbor_portal_url" {
  description = "Harbor web portal URL"
  value       = module.harbor_registry.harbor_portal_url
}

output "harbor_kubectl_commands" {
  description = "Useful kubectl commands for Harbor management"
  value       = module.harbor_registry.kubectl_commands
}

output "harbor_chart_version" {
  description = "Version of the Harbor Helm chart deployed"
  value       = module.harbor_registry.harbor_chart_version
}

output "harbor_services_status" {
  description = "Status of Harbor optional services"
  value       = module.harbor_registry.harbor_services_enabled
}

output "harbor_storage_info" {
  description = "Harbor persistent volume information"
  value       = module.harbor_registry.harbor_persistent_volumes
}

# Docker configuration for Harbor access
output "harbor_docker_config_json" {
  description = "Docker configuration JSON for authenticating with Harbor (base64 encoded)"
  value       = module.harbor_registry.docker_config_json
  sensitive   = true
}

# Deployment Instructions
output "deployment_instructions" {
  description = "Instructions for accessing and using the deployed services"
  value = {
    harbor_access = {
      description = "Harbor Registry Access Instructions"
      web_portal = {
        url      = module.harbor_registry.harbor_portal_url
        username = "admin"
        note     = "Use the harbor_admin_password variable value to log in"
      }
      docker_registry = {
        endpoint = module.harbor_registry.harbor_registry_endpoint
        login_command = "docker login ${module.harbor_registry.harbor_registry_endpoint}"
        note     = "Use 'admin' as username and your harbor_admin_password as password"
      }
      kubectl_access = {
        port_forward = "kubectl port-forward -n ${module.harbor_registry.harbor_namespace} svc/harbor 8080:80"
        local_access = "http://localhost:8080"
      }
    }
    
    next_steps = [
      "1. Access Harbor web portal to create projects",
      "2. Configure Docker to use Harbor as registry",
      "3. Push container images to Harbor projects",
      "4. Configure Kubernetes to pull images from Harbor",
      "5. Set up image vulnerability scanning with Trivy (if enabled)"
    ]
  }
}