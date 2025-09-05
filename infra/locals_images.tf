locals {
  image_repo = "${var.region}-docker.pkg.dev/${var.project_id}/microservices"

  # Compose image refs here so modules don't need explicit image vars
  stt_image          = "${local.image_repo}/stt:${var.image_tag}"
  orchestrator_image = "${local.image_repo}/orchestrator:${var.image_tag}"
}
