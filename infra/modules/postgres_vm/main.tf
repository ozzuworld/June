resource "google_compute_disk" "data" {
  name = "${var.name}-data"
  type = "pd-ssd"
  zone = var.zone
  size = var.disk_size_gb
}

resource "google_compute_instance" "vm" {
  name         = var.name
  zone         = var.zone
  machine_type = var.machine_type

  boot_disk {
    initialize_params {
      image = "debian-cloud/debian-12"
    }
  }

  network_interface {
    network    = var.network
    subnetwork = var.subnetwork
  }

  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -euxo pipefail

    mkfs.ext4 -F /dev/disk/by-id/google-${var.name}-data || true
    mkdir -p /mnt/pgdata
    grep -q '${var.name}-data' /etc/fstab || echo "/dev/disk/by-id/google-${var.name}-data /mnt/pgdata ext4 defaults 0 2" >> /etc/fstab
    mount -a

    apt-get update -y
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io

    docker run -d --name pg \
      --restart=always \
      -e POSTGRES_DB=${var.db_name} \
      -e POSTGRES_USER=${var.db_user} \
      -e POSTGRES_PASSWORD='${var.db_password}' \
      -v /mnt/pgdata:/var/lib/postgresql/data \
      -p 5432:5432 \
      postgres:15
  EOT

  attached_disk {
    source      = google_compute_disk.data.id
    device_name = "${var.name}-data"
  }

  service_account {
    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
  }

  tags = ["postgres"]
}

output "internal_ip" {
  value = google_compute_instance.vm.network_interface[0].network_ip
}
