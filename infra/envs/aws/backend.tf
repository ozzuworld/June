terraform {
  backend "s3" {
    bucket = "CHANGE_ME_tf_state_bucket"
    key    = "june/platform/terraform.tfstate"
    region = "us-east-1"
    dynamodb_table = "CHANGE_ME_tf_lock"
    encrypt = true
  }
}
