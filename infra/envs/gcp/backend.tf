terraform {
  backend "gcs" {
    bucket = "CHANGE_ME_tf_state_bucket"
    prefix = "june/platform"
  }
}
