output "url" {
  value = google_cloud_run_v2_service.this.uri
}

output "service_account_email" {
  description = "Service account used by this Cloud Run service"
  value       = coalesce(
    try(google_cloud_run_v2_service.this.template[0].service_account, null),
    var.service_account,
    ""
  )
}
