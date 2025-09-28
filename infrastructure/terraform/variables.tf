# Project Configuration
variable "project_id" {
  description = "GCP Project ID for June AI Platform"
  type        = string
  default     = "main-buffer-469817-v7"

  validation {
    condition     = length(var.project_id) > 0
    error_message = "Project ID cannot be empty."
  }
}

variable "region" {
  description = "GCP region for resources deployment"
  type        = string
  default     = "us-central1"

  validation {
    condition = contains([
      "us-central1", "us-east1", "us-west1", "us-west2",
      "europe-west1", "europe-west2", "europe-west3",
      "asia-southeast1", "asia-northeast1"
    ], var.region)
    error_message = "Region must be a valid GCP region."
  }
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "Environment must be one of: dev, staging, prod."
  }
}

# Cluster Configuration
variable "cluster_name" {
  description = "Name of the GKE cluster"
  type        = string
  default     = "june-cluster"
  
  validation {
    condition     = can(regex("^[a-z]([a-z0-9-]*[a-z0-9])?$", var.cluster_name))
    error_message = "Cluster name must be a valid GKE cluster name."
  }
}

variable "domain_name" {
  description = "Base domain name for services"
  type        = string
  default     = "june-ai.local"
  
  validation {
    condition     = can(regex("^[a-zA-Z0-9]([a-zA-Z0-9\\-]{0,61}[a-zA-Z0-9])?(\\.[a-zA-Z0-9]([a-zA-Z0-9\\-]{0,61}[a-zA-Z0-9])?)*$", var.domain_name))
    error_message = "Domain name must be a valid FQDN."
  }
}

# GitHub Configuration
variable "github_owner" {
  description = "GitHub repository owner/organization"
  type        = string
  default     = "ozzuworld"

  validation {
    condition     = length(var.github_owner) > 0
    error_message = "GitHub owner cannot be empty."
  }
}

variable "github_repo" {
  description = "GitHub repository name"
  type        = string
  default     = "June"

  validation {
    condition     = length(var.github_repo) > 0
    error_message = "GitHub repository name cannot be empty."
  }
}

variable "build_branch" {
  description = "Git branch pattern for triggering builds"
  type        = string
  default     = "^master$"
}

# Optional: Build configuration overrides
variable "enable_github_triggers" {
  description = "Enable automatic GitHub-triggered builds"
  type        = bool
  default     = false
}

variable "build_timeout_default" {
  description = "Default build timeout in seconds"
  type        = number
  default     = 3600

  validation {
    condition     = var.build_timeout_default >= 600 && var.build_timeout_default <= 7200
    error_message = "Build timeout must be between 600 and 7200 seconds."
  }
}

# Harbor Registry Configuration
variable "harbor_admin_password" {
  description = "Harbor administrator password"
  type        = string
  sensitive   = true
  
  validation {
    condition     = length(var.harbor_admin_password) >= 8
    error_message = "Harbor admin password must be at least 8 characters long."
  }
}

variable "harbor_registry_storage_size" {
  description = "Size of persistent volume for Harbor registry data"
  type        = string
  default     = "100Gi"
  
  validation {
    condition     = can(regex("^[0-9]+[KMGT]i$", var.harbor_registry_storage_size))
    error_message = "Storage size must be in format like '100Gi', '50Mi', etc."
  }
}

variable "harbor_database_storage_size" {
  description = "Size of persistent volume for Harbor database"
  type        = string
  default     = "10Gi"
  
  validation {
    condition     = can(regex("^[0-9]+[KMGT]i$", var.harbor_database_storage_size))
    error_message = "Storage size must be in format like '10Gi', '1Gi', etc."
  }
}

variable "harbor_redis_storage_size" {
  description = "Size of persistent volume for Harbor Redis"
  type        = string
  default     = "5Gi"
  
  validation {
    condition     = can(regex("^[0-9]+[KMGT]i$", var.harbor_redis_storage_size))
    error_message = "Storage size must be in format like '5Gi', '1Gi', etc."
  }
}

# Harbor Feature Toggles
variable "enable_trivy_scanning" {
  description = "Enable Trivy vulnerability scanning in Harbor"
  type        = bool
  default     = true
}

variable "enable_harbor_metrics" {
  description = "Enable Harbor metrics collection"
  type        = bool
  default     = false
}

variable "create_harbor_ingress" {
  description = "Create Kubernetes ingress for Harbor external access"
  type        = bool
  default     = false
}

variable "enable_harbor_tls" {
  description = "Enable TLS for Harbor ingress"
  type        = bool
  default     = false
}

variable "harbor_static_ip_name" {
  description = "Name of the static IP address for Harbor ingress (GCP)"
  type        = string
  default     = ""
}

# Harbor Node Placement (Optional)
variable "harbor_node_selector" {
  description = "Node selector for Harbor pods"
  type        = map(string)
  default     = {}
}

variable "harbor_tolerations" {
  description = "Tolerations for Harbor pods"
  type = list(object({
    key      = optional(string)
    operator = optional(string, "Equal")
    value    = optional(string)
    effect   = optional(string)
  }))
  default = []
}