# Harbor Registry Module Outputs

output "harbor_namespace" {
  description = "Namespace where Harbor is deployed"
  value       = kubernetes_namespace.harbor.metadata[0].name
}

output "harbor_release_name" {
  description = "Name of the Harbor Helm release"
  value       = helm_release.harbor.name
}

output "harbor_external_url" {
  description = "External URL for Harbor registry"
  value       = var.harbor_external_url
}

output "harbor_hostname" {
  description = "Harbor hostname for ingress access"
  value       = var.harbor_hostname
}

output "harbor_admin_secret_name" {
  description = "Name of the Kubernetes secret containing Harbor admin password"
  value       = kubernetes_secret.harbor_admin.metadata[0].name
  sensitive   = true
}

output "harbor_internal_service_name" {
  description = "Name of the internal Harbor service (if created)"
  value       = var.create_internal_service ? kubernetes_service.harbor_internal[0].metadata[0].name : null
}

output "harbor_internal_service_port" {
  description = "Port of the internal Harbor service"
  value       = var.create_internal_service ? 80 : null
}

output "harbor_ingress_name" {
  description = "Name of the Harbor ingress (if created)"
  value       = var.create_ingress ? kubernetes_ingress_v1.harbor_ingress[0].metadata[0].name : null
}

output "harbor_registry_endpoint" {
  description = "Harbor registry endpoint for Docker commands"
  value       = var.create_ingress ? "${var.harbor_hostname}" : "${kubernetes_service.harbor_internal[0].metadata[0].name}.${kubernetes_namespace.harbor.metadata[0].name}.svc.cluster.local"
}

output "harbor_portal_url" {
  description = "Harbor web portal URL"
  value       = var.create_ingress ? "${var.enable_tls ? "https" : "http"}://${var.harbor_hostname}" : var.harbor_external_url
}

output "docker_config_json" {
  description = "Docker configuration JSON for authenticating with Harbor (base64 encoded)"
  value = base64encode(jsonencode({
    auths = {
      (var.create_ingress ? var.harbor_hostname : "${kubernetes_service.harbor_internal[0].metadata[0].name}.${kubernetes_namespace.harbor.metadata[0].name}.svc.cluster.local") = {
        username = "admin"
        password = var.harbor_admin_password
        auth     = base64encode("admin:${var.harbor_admin_password}")
      }
    }
  }))
  sensitive = true
}

# Helm release status and version
output "harbor_chart_version" {
  description = "Version of the Harbor Helm chart deployed"
  value       = helm_release.harbor.version
}

output "harbor_release_status" {
  description = "Status of the Harbor Helm release"
  value       = helm_release.harbor.status
}

# Resource information
output "harbor_persistent_volumes" {
  description = "Information about Harbor persistent volumes"
  value = {
    registry = {
      size          = var.registry_storage_size
      storage_class = var.storage_class
    }
    database = {
      size          = var.database_storage_size
      storage_class = var.storage_class
    }
    redis = {
      size          = var.redis_storage_size
      storage_class = var.storage_class
    }
  }
}

output "harbor_services_enabled" {
  description = "Status of Harbor services"
  value = {
    trivy_scanning = var.enable_trivy_scanning
    metrics        = var.enable_metrics
    ingress        = var.create_ingress
    internal_service = var.create_internal_service
    tls_enabled    = var.enable_tls
  }
}

# kubectl commands for easy access
output "kubectl_commands" {
  description = "Useful kubectl commands for Harbor management"
  value = {
    get_pods     = "kubectl get pods -n ${kubernetes_namespace.harbor.metadata[0].name}"
    get_services = "kubectl get services -n ${kubernetes_namespace.harbor.metadata[0].name}"
    get_pvc      = "kubectl get pvc -n ${kubernetes_namespace.harbor.metadata[0].name}"
    port_forward = "kubectl port-forward -n ${kubernetes_namespace.harbor.metadata[0].name} svc/harbor 8080:80"
    logs_core    = "kubectl logs -n ${kubernetes_namespace.harbor.metadata[0].name} -l app=harbor,component=core"
    logs_registry = "kubectl logs -n ${kubernetes_namespace.harbor.metadata[0].name} -l app=harbor,component=registry"
  }
}