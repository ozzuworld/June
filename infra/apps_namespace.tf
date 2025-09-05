resource "kubernetes_namespace" "apps" {
  metadata { name = "apps" }
}

locals {
  apps_ns          = kubernetes_namespace.apps.metadata[0].name
  orch_host_public = "orch.${var.domain}"
  stt_svc_dns      = "june-stt.${local.apps_ns}.svc.cluster.local"
  tts_svc_dns      = "june-tts.${local.apps_ns}.svc.cluster.local"
  default_port     = 8080
}
