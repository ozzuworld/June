variable "vpc_name" {
  type    = string
  default = "app-vpc"
}

variable "subnet_cidr" {
  type    = string
  default = "10.10.0.0/24"
}


resource "google_compute_network" "vpc" {
  name                    = var.vpc_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "subnet" {
  name          = "${var.vpc_name}-subnet"
  ip_cidr_range = var.subnet_cidr
  region        = var.region
  network       = google_compute_network.vpc.id
}

resource "google_vpc_access_connector" "serverless" {
  name    = "svpc-${var.region}"
  region  = var.region
  network = google_compute_network.vpc.name
  subnet { name = google_compute_subnetwork.subnet.name }
}
