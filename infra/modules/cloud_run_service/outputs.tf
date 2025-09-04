output "uri" { value = google_cloud_run_v2_service.svc.uri }
output "service_account_email" { value = google_service_account.sa.email }
