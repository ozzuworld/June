output "kms_id"      { value = google_kms_crypto_key.key.id }
output "secrets_ref" { value = "use google_secret_manager_secret resources per secret" }
