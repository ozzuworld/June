resource "google_kms_key_ring" "ring" {
  name     = "${var.name}-ring"
  location = var.region
}
resource "google_kms_crypto_key" "key" {
  name            = "${var.name}-key"
  key_ring        = google_kms_key_ring.ring.id
  rotation_period = "2592000s" # 30 days
}
# Placeholder secret (you will add IAM+actual secrets as needed)
output "kms_id"      { value = google_kms_crypto_key.key.id }
output "secrets_ref" { value = "use google_secret_manager_secret resources per secret" }
