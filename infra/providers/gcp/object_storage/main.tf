resource "google_storage_bucket" "bucket" {
  name                        = var.name
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false
}
output "bucket_name" { value = google_storage_bucket.bucket.name }
