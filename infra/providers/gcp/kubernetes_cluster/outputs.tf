output "endpoint"        { value = google_container_cluster.this.endpoint }
output "ca_cert"         { value = google_container_cluster.this.master_auth[0].cluster_ca_certificate }
output "kube_client_cmd" { value = "gcloud container clusters get-credentials ${var.name} --region ${var.region} --project ${var.project_id}" }
