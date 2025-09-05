resource "kubernetes_horizontal_pod_autoscaler_v2" "orch" {
  metadata { name = "june-orchestrator"; namespace = local.apps_ns }
  spec {
    scale_target_ref { api_version = "apps/v1" kind = "Deployment" name = kubernetes_deployment.orch.metadata[0].name }
    min_replicas = 2
    max_replicas = 10
    metric { type = "Resource" resource { name = "cpu" target { type = "Utilization" average_utilization = 70 } } }
  }
}

resource "kubernetes_horizontal_pod_autoscaler_v2" "stt" {
  metadata { name = "june-stt"; namespace = local.apps_ns }
  spec {
    scale_target_ref { api_version = "apps/v1" kind = "Deployment" name = kubernetes_deployment.stt.metadata[0].name }
    min_replicas = 2
    max_replicas = 10
    metric { type = "Resource" resource { name = "cpu" target { type = "Utilization" average_utilization = 70 } } }
  }
}

resource "kubernetes_horizontal_pod_autoscaler_v2" "tts" {
  metadata { name = "june-tts"; namespace = local.apps_ns }
  spec {
    scale_target_ref { api_version = "apps/v1" kind = "Deployment" name = kubernetes_deployment.tts.metadata[0].name }
    min_replicas = 2
    max_replicas = 10
    metric { type = "Resource" resource { name = "cpu" target { type = "Utilization" average_utilization = 70 } } }
  }
}
