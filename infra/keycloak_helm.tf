locals {
  kc_hostname = "auth.${var.domain}"
}

resource "helm_release" "keycloak" {
  name       = "keycloak"
  namespace  = kubernetes_namespace.auth.metadata[0].name
  repository = "https://charts.bitnami.com/bitnami"
  chart      = "keycloak"

  values = [yamlencode({
    image = {
      registry   = "quay.io"
      repository = "keycloak/keycloak"
      tag        = "24.0"
    }
    auth = {
      adminUser                 = "admin"
      existingSecret            = kubernetes_secret.keycloak_admin.metadata[0].name
      existingSecretPasswordKey = "password"
    }
    proxy = "edge"

    extraEnvVars = [
      { name = "KC_DB", value = "postgres" },
      { name = "KC_DB_URL", value = local.kc_db_url },
      { name = "KC_HOSTNAME", value = local.kc_hostname },
      {
        name = "KC_DB_USERNAME",
        valueFrom = {
          secretKeyRef = { name = kubernetes_secret.keycloak_db.metadata[0].name, key = "username" }
        }
      },
      {
        name = "KC_DB_PASSWORD",
        valueFrom = {
          secretKeyRef = { name = kubernetes_secret.keycloak_db.metadata[0].name, key = "password" }
        }
      },
      { name = "KC_HEALTH_ENABLED",  value = "true" },
      { name = "KC_METRICS_ENABLED", value = "true" }
    ]

    service = { type = "ClusterIP", ports = { http = 8080 } }

    ingress = {
      enabled          = true
      ingressClassName = "nginx"
      hostname         = local.kc_hostname
      path             = "/"
      pathType         = "Prefix"
      tls              = false
      annotations      = {}
    }

    resources = {
      requests = { cpu = "500m", memory = "1Gi" }
      limits   = { cpu = "2",    memory = "2Gi" }
    }
  })]

  depends_on = [
    helm_release.nginx_ingress,
    kubernetes_secret.keycloak_admin,
    kubernetes_secret.keycloak_db,
    helm_release.postgresql
  ]
}
