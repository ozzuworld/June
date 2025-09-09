terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.38"
    }
  }
  backend "remote" {}
}

provider "google" {
  project = var.seed_project_id
}

resource "google_project" "workload" {
  name            = "june-workload-${var.suffix}"
  project_id      = "june-${var.suffix}"
  org_id          = var.org_id
  billing_account = var.billing_account
  labels = {
    env   = "ephemeral"
    batch = var.batch
  }
}

resource "google_project_service" "apis" {
  for_each = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "compute.googleapis.com"
  ])
  project            = google_project.workload.project_id
  service            = each.key
  disable_on_destroy = false
}

output "project_id" { value = google_project.workload.project_id }
