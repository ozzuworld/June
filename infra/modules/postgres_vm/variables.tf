variable "project_id" { type = string }
variable "region"     { type = string }
variable "zone"       { type = string }

variable "name"       { type = string }
variable "network"    { type = string }
variable "subnetwork" { type = string }

variable "db_name" {
  type    = string
  default = "keycloak"
}

variable "db_user" {
  type    = string
  default = "keycloak"
}

variable "db_password" {
  type      = string
  sensitive = true
}

variable "disk_size_gb" {
  type    = number
  default = 50
}

variable "machine_type" {
  type    = string
  default = "e2-medium"
}
