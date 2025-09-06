terraform {
  required_providers {
    google = { source = "hashicorp/google", version = "~> 5.40" }
  }
}

resource "google_container_cluster" "this" {
  name     = var.name
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1

  network    = var.network_id
  subnetwork = var.subnet_id

  release_channel { channel = "REGULAR" }
  ip_allocation_policy {}

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "pools" {
  for_each   = { for p in var.node_pools : p.name => p }
  name       = each.value.name
  location   = var.region
  cluster    = google_container_cluster.this.name

  node_config {
    machine_type = each.value.machine
    disk_size_gb = each.value.disk_gb
    spot         = each.value.spot
    oauth_scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    labels       = { role = "general" }
    tags         = ["k8s-node"]
  }

  autoscaling {
    min_node_count = each.value.min
    max_node_count = each.value.max
  }
}

output "endpoint"        { value = google_container_cluster.this.endpoint }
output "ca_cert"         { value = google_container_cluster.this.master_auth[0].cluster_ca_certificate }
output "kube_client_cmd" { value = "gcloud container clusters get-credentials ${var.name} --region ${var.region} --project ${var.project_id}" }
output "kubeconfig"      { value = null } # typically retrieved via gcloud
