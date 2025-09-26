# infrastructure/terraform/variables.tf
# Centralized variable definitions for June AI Platform

variable "project_id" {
  description = "GCP Project ID"
  type        = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "Project ID must follow GCP naming conventions."
  }
}

variable "region" {
  description = "GCP Region for resources"
  type        = string
  default     = "us-central1"
  validation {
    condition = contains([
      "us-central1", "us-east1", "us-west1", "us-west2",
      "europe-west1", "europe-west2", "asia-east1"
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
    error_message = "Environment must be dev, staging, or prod."
  }
}

variable "domain" {
  description = "Base domain for June services"
  type        = string
  default     = "allsafe.world"
  validation {
    condition     = can(regex("^[a-z0-9.-]+\\.[a-z]{2,}$", var.domain))
    error_message = "Domain must be a valid domain name."
  }
}

variable "enable_autopilot" {
  description = "Enable GKE Autopilot mode"
  type        = bool
  default     = true
}

variable "node_count" {
  description = "Number of nodes in the default node pool (ignored if autopilot is enabled)"
  type        = number
  default     = 1
  validation {
    condition     = var.node_count >= 1 && var.node_count <= 10
    error_message = "Node count must be between 1 and 10."
  }
}

variable "machine_type" {
  description = "GCE machine type for nodes (ignored if autopilot is enabled)"
  type        = string
  default     = "e2-small"
}

variable "disk_size_gb" {
  description = "Disk size in GB for nodes (ignored if autopilot is enabled)"
  type        = number
  default     = 30
  validation {
    condition     = var.disk_size_gb >= 10 && var.disk_size_gb <= 200
    error_message = "Disk size must be between 10 and 200 GB."
  }
}

variable "enable_monitoring" {
  description = "Enable Google Cloud Monitoring"
  type        = bool
  default     = true
}

variable "enable_logging" {
  description = "Enable Google Cloud Logging"
  type        = bool
  default     = true
}

variable "enable_network_policy" {
  description = "Enable Kubernetes Network Policy"
  type        = bool
  default     = true
}

variable "authorized_networks" {
  description = "List of CIDR blocks that can access the cluster API server"
  type = list(object({
    cidr_block   = string
    display_name = string
  }))
  default = [
    {
      cidr_block   = "0.0.0.0/0"
      display_name = "All networks"
    }
  ]
}

variable "resource_labels" {
  description = "Additional labels to apply to all resources"
  type        = map(string)
  default     = {}
}

variable "backup_retention_days" {
  description = "Number of days to retain backups"
  type        = number
  default     = 30
  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 365
    error_message = "Backup retention must be between 1 and 365 days."
  }
}

variable "ssl_policy" {
  description = "SSL policy for HTTPS load balancer"
  type        = string
  default     = "MODERN"
  validation {
    condition     = contains(["COMPATIBLE", "MODERN", "RESTRICTED"], var.ssl_policy)
    error_message = "SSL policy must be COMPATIBLE, MODERN, or RESTRICTED."
  }
}