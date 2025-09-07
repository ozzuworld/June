
output "wif_provider_resource" {
  value = "projects/${var.project_number}/locations/global/workloadIdentityPools/${google_iam_workload_identity_pool.github_pool.workload_identity_pool_id}/providers/${google_iam_workload_identity_pool_provider.github_provider.workload_identity_pool_provider_id}"
}
output "deployer_sa_email" {
  value = google_service_account.github_deployer.email
}
