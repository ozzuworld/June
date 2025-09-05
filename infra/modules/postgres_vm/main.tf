resource "google_compute_disk" "data" {
  name = "${var.name}-data"
  type = "pd-ssd"
  zone = var.zone
  size = var.disk_size_gb
}

resource "google_compute_instance" "vm" {
  name                = var.name
  zone                = var.zone
  machine_type        = var.machine_type
  can_ip_forward      = false
  deletion_protection = false

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
    preemptible         = false
  }

  # Boot
  boot_disk {
    initialize_params { image = "debian-cloud/debian-12" }
  }

  # Private only (no external IP)
  network_interface {
    network    = var.network
    subnetwork = var.subnetwork
  }

  # Mount PD and run Postgres in Docker pinned to that mount
  metadata_startup_script = <<-EOT
    #!/bin/bash
    set -euxo pipefail

    # format & mount persistent data disk
    mkfs.ext4 -F /dev/disk/by-id/google-${var.name}-data || true
    mkdir -p /mnt/pgdata
    grep -q '${var.name}-data' /etc/fstab || echo "/dev/disk/by-id/google-${var.name}-data /mnt/pgdata ext4 defaults 0 2" >> /etc/fstab
    mount -a

    # install docker
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io

    # run postgres container with persistent volume and auto-restart
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

  service_account { scopes = ["https://www.googleapis.com/auth/cloud-platform"] }
  tags = ["postgres"]
}

# Internal IP to reach from Cloud Run via VPC connector
output "internal_ip" {
  value = google_compute_instance.vm.network_interface[0].network_ip
}
