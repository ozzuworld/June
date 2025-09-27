variable "project_id" {
  description = "GCP Project ID"
  type        = string
}

variable "region" {
  description = "GCP Region"
  type        = string
}

variable "repository_id" {
  description = "Artifact Registry repository ID"
  type        = string
}

variable "description" {
  description = "Repository description"
  type        = string
  default     = "Docker repository for microservices"
}

variable "labels" {
  description = "Labels to apply to the repository"
  type        = map(string)
  default     = {}
}

variable "reader_members" {
  description = "List of members with reader access"
  type        = list(string)
  default     = []
}

variable "writer_members" {
  description = "List of members with writer access"
  type        = list(string)
  default     = []
}
