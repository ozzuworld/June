variable "image_idp" { type = string }
variable "KC_BASE_URL" { type = string } # https://june-idp-<hash>-us-central1.a.run.app or custom domain
variable "KC_DB_URL" { type = string }   # jdbc:postgresql://HOST:5432/DB?sslmode=require
variable "KC_DB_USERNAME" { type = string }

module "idp" {
  source       = "git::https://github.com/ozzuworld/June.git//infra/modules/cloud_run_service?ref=master"
  service_name = "june-idp"
  region       = var.region
  image        = var.image_idp

  service_account  = google_service_account.idp_sa.email
  session_affinity = true

  cpu           = "1"
  memory        = "2Gi"
  port          = 8080
  min_instances = 0
  max_instances = 3

  args = [
    "start",
    "--http-enabled=true",
    "--proxy-headers=xforwarded",
    "--hostname=${var.KC_BASE_URL}"
  ]

  env = {
    KC_DB                       = "postgres"
    KC_DB_URL                   = var.KC_DB_URL
    KC_DB_USERNAME              = var.KC_DB_USERNAME
    KC_BOOTSTRAP_ADMIN_USERNAME = "admin"
    KC_BOOTSTRAP_ADMIN_PASSWORD = "bootstrap-temp"
  }

  env_secrets = {
    KC_DB_PASSWORD = { secret = "KC_DB_PASSWORD", version = "latest" }
  }
}

output "idp_url" {
  value = module.idp.url
}


