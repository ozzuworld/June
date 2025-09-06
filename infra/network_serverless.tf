# Serverless VPC Access connector only (reuses VPC/Subnet from network_gke.tf)

resource "google_vpc_access_connector" "serverless" {
  name   = "svpc-${var.region}"
  region = var.region

  # Reuse existing network/subnet created in network_gke.tf
  network = google_compute_network.vpc.name

  subnet {
    name = google_compute_subnetwork.subnet.name
  }
}
