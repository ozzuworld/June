resource "google_container_cluster" "gke" {
  name             = "june-autopilot"
  location         = var.region
  network          = google_compute_network.vpc.self_link
  subnetwork       = google_compute_subnetwork.subnet.self_link
  enable_autopilot = true

  networking_mode = "VPC_NATIVE"
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }
}
