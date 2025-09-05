locals {
  db_namespace = "db"
}

resource "kubernetes_namespace" "db" {
  metadata { name = local.db_namespace }
}

# Secret with expected keys by Bitnami chart when using existingSecret
resource "kubernetes_secret" "pg_auth" {
  metadata {
    name      = "pg-auth"
    namespace = kubernetes_namespace.db.metadata[0].name
  }
  type = "Opaque"
  data = {
    "postgres-password" = local.kc_db_password_effective
    "password"          = local.kc_db_password_effective
    "username"          = var.kc_db_user
    "database"          = var.kc_db_name
  }
}

resource "helm_release" "postgresql" {
  name       = "postgresql"
  namespace  = kubernetes_namespace.db.metadata[0].name
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "postgresql"

  values = [yamlencode({
    global = {
      storageClass = "standard-rwo"
    }
    primary = {
      persistence = {
        enabled     = true
        size        = "50Gi"
        accessModes = ["ReadWriteOnce"]
      }
      resources = {
        requests = { cpu = "250m", memory = "512Mi" }
        limits   = { cpu = "1",    memory = "1Gi" }
      }
    }
    auth = {
      existingSecret = kubernetes_secret.pg_auth.metadata[0].name
      username       = var.kc_db_user
      database       = var.kc_db_name
    }
  })]

  depends_on = [kubernetes_secret.pg_auth]
}

# Connection info exported as locals
locals {
  pg_service_dns = "${helm_release.postgresql.name}-postgresql.${kubernetes_namespace.db.metadata[0].name}.svc.cluster.local"
  kc_db_url      = "jdbc:postgresql://${local.pg_service_dns}:5432/${var.kc_db_name}"
}
