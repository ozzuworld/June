# Harbor Registry Module Variables

variable "harbor_namespace" {
  description = "Kubernetes namespace for Harbor deployment"
  type        = string
  default     = "harbor-system"
  
  validation {
    condition     = can(regex("^[a-z0-9]([-a-z0-9]*[a-z0-9])?$", var.harbor_namespace))
    error_message = "Harbor namespace must be a valid Kubernetes namespace name."
  }
}

variable "harbor_chart_version" {
  description = "Harbor Helm chart version to deploy"
  type        = string
  default     = "1.15.0"
  
  validation {
    condition     = can(regex("^[0-9]+\\.[0-9]+\\.[0-9]+$", var.harbor_chart_version))
    error_message = "Chart version must be in semantic version format (e.g., 1.15.0)."
  }
}

variable "harbor_admin_password" {
  description = "Harbor administrator password"
  type        = string
  sensitive   = true
  
  validation {
    condition     = length(var.harbor_admin_password) >= 8
    error_message = "Harbor admin password must be at least 8 characters long."
  }
}

variable "harbor_external_url" {
  description = "External URL for Harbor registry"
  type        = string
  default     = "http://harbor.local"
  
  validation {
    condition     = can(regex("^https?://", var.harbor_external_url))
    error_message = "External URL must start with http:// or https://."
  }
}

variable "harbor_hostname" {
  description = "Hostname for Harbor ingress (if enabled)"
  type        = string
  default     = "harbor.local"
  
  validation {
    condition     = can(regex("^[a-zA-Z0-9]([a-zA-Z0-9\\-]{0,61}[a-zA-Z0-9])?(\\.[a-zA-Z0-9]([a-zA-Z0-9\\-]{0,61}[a-zA-Z0-9])?)*$", var.harbor_hostname))
    error_message = "Harbor hostname must be a valid FQDN."
  }
}

# Storage Configuration
variable "storage_class" {
  description = "Kubernetes storage class for Harbor persistent volumes"
  type        = string
  default     = "standard-rwo"
}

variable "registry_storage_size" {
  description = "Size of persistent volume for Harbor registry data"
  type        = string
  default     = "100Gi"
  
  validation {
    condition     = can(regex("^[0-9]+[KMGT]i$", var.registry_storage_size))
    error_message = "Storage size must be in format like '100Gi', '50Mi', etc."
  }
}

variable "database_storage_size" {
  description = "Size of persistent volume for Harbor database"
  type        = string
  default     = "10Gi"
  
  validation {
    condition     = can(regex("^[0-9]+[KMGT]i$", var.database_storage_size))
    error_message = "Storage size must be in format like '10Gi', '1Gi', etc."
  }
}

variable "redis_storage_size" {
  description = "Size of persistent volume for Harbor Redis"
  type        = string
  default     = "5Gi"
  
  validation {
    condition     = can(regex("^[0-9]+[KMGT]i$", var.redis_storage_size))
    error_message = "Storage size must be in format like '5Gi', '1Gi', etc."
  }
}

# Feature Flags
variable "enable_trivy_scanning" {
  description = "Enable Trivy vulnerability scanning"
  type        = bool
  default     = true
}

variable "enable_metrics" {
  description = "Enable Harbor metrics collection"
  type        = bool
  default     = false
}

variable "create_ingress" {
  description = "Create Kubernetes ingress for external access"
  type        = bool
  default     = false
}

variable "create_internal_service" {
  description = "Create internal ClusterIP service for Harbor"
  type        = bool
  default     = true
}

# Networking Configuration
variable "static_ip_name" {
  description = "Name of the static IP address for ingress (GCP)"
  type        = string
  default     = ""
}

variable "enable_tls" {
  description = "Enable TLS for Harbor ingress"
  type        = bool
  default     = false
}

variable "tls_secret_name" {
  description = "Name of the Kubernetes secret containing TLS certificates"
  type        = string
  default     = "harbor-tls"
}

variable "ingress_annotations" {
  description = "Additional annotations for Harbor ingress"
  type        = map(string)
  default     = {}
}

# Node and Pod Configuration
variable "node_selector" {
  description = "Node selector for Harbor pods"
  type        = map(string)
  default     = {}
}

variable "tolerations" {
  description = "Tolerations for Harbor pods"
  type = list(object({
    key      = optional(string)
    operator = optional(string, "Equal")
    value    = optional(string)
    effect   = optional(string)
  }))
  default = []
}

# Labels
variable "labels" {
  description = "Common labels to apply to all resources"
  type        = map(string)
  default = {
    "app.kubernetes.io/managed-by" = "terraform"
    "app.kubernetes.io/part-of"    = "harbor-registry"
  }
}

# GKE Specific
variable "cluster_name" {
  description = "Name of the GKE cluster"
  type        = string
}

variable "cluster_location" {
  description = "Location of the GKE cluster"
  type        = string
}

variable "project_id" {
  description = "GCP Project ID"
  type        = string
}