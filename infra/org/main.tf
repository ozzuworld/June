terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 5.38"
    }
  }
  backend "remote" {} # Fill in Terraform Cloud workspace in terraform init
}

provider "google" {
  project = var.seed_project_id
}

# Create a new project for the month
resource "google_project" "workload" {
  name       = "june-workload-${var.month_suffix}"
  project_id = "june-${var.month_suffix}"
  org_id     = var.org_id
  billing_account = var.billing_account
  labels = {
    env   = "ephemeral"
    month = var.month_suffix
  }
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "iam.googleapis.com",
    "cloudbuild.googleapis.com",
    "compute.googleapis.com",
    "servicenetworking.googleapis.com"
  ])
  project = google_project.workload.project_id
  service = each.key
  disable_on_destroy = false
}

output "project_id" { value = google_project.workload.project_id }
output "region"     { value = var.default_region }
