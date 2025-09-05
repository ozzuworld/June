resource "kubernetes_namespace" "auth" {
  metadata { name = "auth" }
}

# Generate KC admin password if not set
resource "random_password" "kc_admin" {
  length  = 24
  special = false
}

locals {
  kc_admin_password_effective = var.kc_admin_password != "" ? var.kc_admin_password : random_password.kc_admin.result
}

resource "kubernetes_secret" "keycloak_admin" {
  metadata {
    name      = "keycloak-admin"
    namespace = kubernetes_namespace.auth.metadata[0].name
  }
  type = "Opaque"
  data = {
    password = local.kc_admin_password_effective
  }
}

# DB secret for Keycloak
resource "kubernetes_secret" "keycloak_db" {
  metadata {
    name      = "keycloak-db"
    namespace = kubernetes_namespace.auth.metadata[0].name
  }
  type = "Opaque"
  data = {
    username = var.kc_db_user
    password = local.kc_db_password_effective  # <- use the local (auto-gen if blank)
  }
}

resource "random_password" "kc_db" {
  length  = 24
  special = false
}

locals {
  kc_db_password_effective = var.kc_db_password != "" ? var.kc_db_password : random_password.kc_db.result
}
