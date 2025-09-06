# Orchestrator (public)
resource "kubernetes_service_account" "orch" {
  metadata {
    name      = "june-orchestrator"
    namespace = local.apps_ns
  }
}

resource "kubernetes_deployment" "orch" {
  metadata {
    name      = "june-orchestrator"
    namespace = local.apps_ns
    labels = {
      app = "june-orchestrator"
    }
  }

  spec {
    replicas = 2

    selector {
      match_labels = { app = "june-orchestrator" }
    }

    template {
      metadata {
        labels = { app = "june-orchestrator" }
      }

      spec {
        service_account_name = kubernetes_service_account.orch.metadata[0].name

        container {
          name              = "app"
          image             = var.orchestrator_image
          image_pull_policy = "IfNotPresent"

          port {
            container_port = local.default_port
          }

          liveness_probe {
            tcp_socket {
              port = local.default_port
            }
            initial_delay_seconds = 20
            period_seconds        = 10
          }

          readiness_probe {
            tcp_socket {
              port = local.default_port
            }
            initial_delay_seconds = 10
            period_seconds        = 5
          }

          resources {
            requests = {
              cpu    = "250m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "1000m"
              memory = "1Gi"
            }
          }

          env {
            name  = "PORT"
            value = tostring(local.default_port)
          }

          env {
            name  = "STT_BASE_URL"
            value = "http://${local.stt_svc_dns}:${local.default_port}"
          }

          env {
            name  = "TTS_BASE_URL"
            value = "http://${local.tts_svc_dns}:${local.default_port}"
          }

          env {
            name  = "ORCH_STREAM_TTS"
            value = var.orch_stream_tts ? "true" : "false"
          }

          env {
            name  = "GCP_PROJECT"
            value = var.project_id
          }

          env {
            name  = "FIREBASE_PROJECT_ID"
            value = var.firebase_project_id
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "orch" {
  metadata {
    name      = "june-orchestrator"
    namespace = local.apps_ns
    labels    = { app = "june-orchestrator" }
  }

  spec {
    selector = { app = "june-orchestrator" }

    port {
      name        = "http"
      port        = 80
      target_port = local.default_port
    }

    type = "ClusterIP"
  }
}

resource "kubernetes_ingress_v1" "orch" {
  metadata {
    name      = "orch-public"
    namespace = local.apps_ns
    annotations = {
      "kubernetes.io/ingress.class" = "nginx"
    }
  }

  spec {
    rule {
      host = local.orch_host_public
      http {
        path {
          path      = "/"
          path_type = "Prefix"

          backend {
            service {
              name = kubernetes_service.orch.metadata[0].name
              port {
                number = 80
              }
            }
          }
        }
      }
    }
  }

  depends_on = [helm_release.nginx_ingress]
}

# STT (internal)
resource "kubernetes_service_account" "stt" {
  metadata {
    name      = "june-stt"
    namespace = local.apps_ns
  }
}

resource "kubernetes_deployment" "stt" {
  metadata {
    name      = "june-stt"
    namespace = local.apps_ns
    labels    = { app = "june-stt" }
  }

  spec {
    replicas = 2

    selector {
      match_labels = { app = "june-stt" }
    }

    template {
      metadata {
        labels = { app = "june-stt" }
      }

      spec {
        service_account_name = kubernetes_service_account.stt.metadata[0].name

        container {
          name              = "app"
          image             = var.stt_image
          image_pull_policy = "IfNotPresent"

          port {
            container_port = local.default_port
          }

          liveness_probe {
            tcp_socket {
              port = local.default_port
            }
            initial_delay_seconds = 20
            period_seconds        = 10
          }

          readiness_probe {
            tcp_socket {
              port = local.default_port
            }
            initial_delay_seconds = 10
            period_seconds        = 5
          }

          resources {
            requests = {
              cpu    = "250m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "1000m"
              memory = "1Gi"
            }
          }

          env {
            name  = "PORT"
            value = tostring(local.default_port)
          }

          env {
            name  = "GCP_PROJECT"
            value = var.project_id
          }

          env {
            name  = "FIREBASE_PROJECT_ID"
            value = var.firebase_project_id
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "stt" {
  metadata {
    name      = "june-stt"
    namespace = local.apps_ns
    labels    = { app = "june-stt" }
  }

  spec {
    selector = { app = "june-stt" }

    port {
      name        = "http"
      port        = local.default_port
      target_port = local.default_port
    }

    type = "ClusterIP"
  }
}

# TTS (internal)
resource "kubernetes_service_account" "tts" {
  metadata {
    name      = "june-tts"
    namespace = local.apps_ns
  }
}

resource "kubernetes_deployment" "tts" {
  metadata {
    name      = "june-tts"
    namespace = local.apps_ns
    labels    = { app = "june-tts" }
  }

  spec {
    replicas = 2

    selector {
      match_labels = { app = "june-tts" }
    }

    template {
      metadata {
        labels = { app = "june-tts" }
      }

      spec {
        service_account_name = kubernetes_service_account.tts.metadata[0].name

        container {
          name              = "app"
          image             = var.tts_image
          image_pull_policy = "IfNotPresent"

          port {
            container_port = local.default_port
          }

          liveness_probe {
            tcp_socket {
              port = local.default_port
            }
            initial_delay_seconds = 20
            period_seconds        = 10
          }

          readiness_probe {
            tcp_socket {
              port = local.default_port
            }
            initial_delay_seconds = 10
            period_seconds        = 5
          }

          resources {
            requests = {
              cpu    = "250m"
              memory = "256Mi"
            }
            limits = {
              cpu    = "1000m"
              memory = "1Gi"
            }
          }

          env {
            name  = "PORT"
            value = tostring(local.default_port)
          }

          env {
            name  = "GCP_PROJECT"
            value = var.project_id
          }

          env {
            name  = "FIREBASE_PROJECT_ID"
            value = var.firebase_project_id
          }
        }
      }
    }
  }
}

resource "kubernetes_service" "tts" {
  metadata {
    name      = "june-tts"
    namespace = local.apps_ns
    labels    = { app = "june-tts" }
  }

  spec {
    selector = { app = "june-tts" }

    port {
      name        = "http"
      port        = local.default_port
      target_port = local.default_port
    }

    type = "ClusterIP"
  }
}
